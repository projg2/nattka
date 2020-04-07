# (c) 2020 Michał Górny
# 2-clause BSD license

"""Dependency graph tests"""

import typing
import unittest
import unittest.mock

try:
    import networkx as nx
except ImportError:
    nx = None
else:
    from nattka.depgraph import DepType, CycleTuple, get_ordered_nodes


@unittest.skipIf(nx is None, 'networkx required for depgraph support')
class DepGraphOrderingTests(unittest.TestCase):
    def test_simple(self):
        """Test simple A -> B -> C graph"""
        graph = nx.DiGraph()
        graph.add_nodes_from('ABC')
        graph.add_edge('A', 'B', dep=DepType.DEPEND, level=0)
        graph.add_edge('B', 'C', dep=DepType.DEPEND, level=0)
        self.assertEqual(
            list(get_ordered_nodes(graph)),
            ['C', 'B', 'A'])

    def test_loose(self):
        """Test graph with unconnected nodes"""
        graph = nx.DiGraph()
        graph.add_nodes_from('ABCD')
        graph.add_edge('A', 'B', dep=DepType.DEPEND, level=0)

        out = list(get_ordered_nodes(graph))
        # verify that all nodes are present
        self.assertEqual(sorted(out), list('ABCD'))
        # verify relative order
        self.assertLess(out.index('B'), out.index('A'))

    def test_multi(self):
        """
        Test graph with multiple subtrees

             A
            ↙↓↘
           B E G
          ↙↓ ↓
         C D F
        """

        graph = nx.DiGraph()
        graph.add_nodes_from('ABCDEFG')
        graph.add_edge('A', 'B', dep=DepType.DEPEND, level=0)
        graph.add_edge('B', 'C', dep=DepType.DEPEND, level=0)
        graph.add_edge('B', 'D', dep=DepType.DEPEND, level=0)
        graph.add_edge('A', 'E', dep=DepType.DEPEND, level=0)
        graph.add_edge('E', 'F', dep=DepType.DEPEND, level=0)
        graph.add_edge('A', 'G', dep=DepType.DEPEND, level=0)

        out = list(get_ordered_nodes(graph))
        # verify that all nodes are present
        self.assertEqual(sorted(out), list('ABCDEFG'))
        # A must always come last
        self.assertEqual(out[-1], 'A')
        # verify relative order
        self.assertLess(out.index('C'), out.index('B'))
        self.assertLess(out.index('D'), out.index('B'))
        self.assertLess(out.index('F'), out.index('E'))

    def test_cross(self):
        """
        Test graph with crossed subtrees (common dependencies)

             A
            ↙↓↘
           B ↓ G
          ↙↓↘↓ ↑
         C D E ↑
             ↓↗
             F
        """

        graph = nx.DiGraph()
        graph.add_nodes_from('ABCDEFG')
        graph.add_edge('A', 'B', dep=DepType.DEPEND, level=0)
        graph.add_edge('B', 'C', dep=DepType.DEPEND, level=0)
        graph.add_edge('B', 'D', dep=DepType.DEPEND, level=0)
        graph.add_edge('A', 'E', dep=DepType.DEPEND, level=0)
        graph.add_edge('B', 'E', dep=DepType.DEPEND, level=0)
        graph.add_edge('E', 'F', dep=DepType.DEPEND, level=0)
        graph.add_edge('A', 'G', dep=DepType.DEPEND, level=0)
        graph.add_edge('F', 'G', dep=DepType.DEPEND, level=0)

        out = list(get_ordered_nodes(graph))
        # verify that all nodes are present
        self.assertEqual(sorted(out), list('ABCDEFG'))
        # A must always come last
        self.assertEqual(out[-1], 'A')
        # verify relative order
        self.assertLess(out.index('C'), out.index('B'))
        self.assertLess(out.index('D'), out.index('B'))
        self.assertLess(out.index('E'), out.index('B'))
        self.assertLess(out.index('F'), out.index('E'))
        self.assertLess(out.index('G'), out.index('F'))

    def test_circular(self):
        """
        Simple circular dependency

        A → B → C
         ↖←←←←←↙ (PDEPEND)
        """

        graph = nx.DiGraph()
        graph.add_nodes_from('ABC')
        graph.add_edge('A', 'B', dep=DepType.DEPEND, level=0)
        graph.add_edge('B', 'C', dep=DepType.DEPEND, level=0)
        graph.add_edge('C', 'A', dep=DepType.PDEPEND, level=0)

        # check both forward and reverse graph to make sure it is
        # actually resolving circular dependencies and not just
        # producing incidentally correct output
        cycles: typing.List[CycleTuple] = []
        self.assertEqual(
            list(get_ordered_nodes(graph.copy(), cycles.append)),
            ['C', 'B', 'A'])
        self.assertEqual(
            cycles,
            [([('A', 'B'), ('B', 'C'), ('C', 'A')], ('C', 'A'))])

        cycles = []
        self.assertEqual(
            list(get_ordered_nodes(graph.reverse())),
            ['A', 'B', 'C'])
        self.assertEqual(
            cycles,
            [])

    def test_multi_circular(self):
        """
        Complex dependency graph with multiple circular dependencies

           B←A
           ↓↗↓↘
           C D→F
             ↕↖↓
             E G
        """

        graph = nx.DiGraph()
        graph.add_nodes_from('ABCDEFG')
        graph.add_edge('A', 'B', dep=DepType.DEPEND, level=0)
        graph.add_edge('B', 'C', dep=DepType.DEPEND, level=0)
        graph.add_edge('C', 'A', dep=DepType.RDEPEND, level=0)
        graph.add_edge('A', 'D', dep=DepType.DEPEND, level=0)
        graph.add_edge('D', 'E', dep=DepType.DEPEND, level=0)
        graph.add_edge('D', 'F', dep=DepType.RDEPEND, level=0)
        graph.add_edge('E', 'D', dep=DepType.PDEPEND, level=0)
        graph.add_edge('A', 'F', dep=DepType.RDEPEND, level=0)
        graph.add_edge('F', 'G', dep=DepType.DEPEND, level=0)
        graph.add_edge('G', 'D', dep=DepType.DEPEND, level=0)

        cycles: typing.List[CycleTuple] = []
        out = list(get_ordered_nodes(graph, cycles.append))
        # verify that all nodes are present
        self.assertEqual(sorted(out), list('ABCDEFG'))
        # A must always come last
        self.assertEqual(out[-1], 'A')
        # verify relative order
        self.assertLess(out.index('C'), out.index('B'))
        self.assertLess(out.index('D'), out.index('G'))
        self.assertLess(out.index('E'), out.index('D'))
        self.assertLess(out.index('G'), out.index('F'))
        # verify cycle resolution
        self.assertEqual(
            sorted(cycles),
            [([('A', 'B'), ('B', 'C'), ('C', 'A')], ('C', 'A')),
             ([('D', 'E'), ('E', 'D')], ('E', 'D')),
             ([('D', 'F'), ('F', 'G'), ('G', 'D')], ('D', 'F')),
             ])

    def test_circular_level(self):
        """
        Simple circular dependency with different USE levels

        A → B → C
         ↖←←←←←↙
        """

        graph = nx.DiGraph()
        graph.add_nodes_from('ABC')
        graph.add_edge('A', 'B', dep=DepType.DEPEND, level=0)
        graph.add_edge('B', 'C', dep=DepType.DEPEND, level=0)
        graph.add_edge('C', 'A', dep=DepType.DEPEND, level=1)

        # check both forward and reverse graph to make sure it is
        # actually resolving circular dependencies and not just
        # producing incidentally correct output
        cycles: typing.List[CycleTuple] = []
        self.assertEqual(
            list(get_ordered_nodes(graph.copy(), cycles.append)),
            ['C', 'B', 'A'])
        self.assertEqual(
            cycles,
            [([('A', 'B'), ('B', 'C'), ('C', 'A')], ('C', 'A'))])

        cycles = []
        self.assertEqual(
            list(get_ordered_nodes(graph.reverse())),
            ['A', 'B', 'C'])
        self.assertEqual(
            cycles,
            [])
