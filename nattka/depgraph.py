# (c) 2020 Michał Górny
# 2-clause BSD license

"""Dependency graph support"""

import enum
import typing

import networkx as nx


class DepType(enum.IntEnum):
    """Dependency type, strongest first"""

    BDEPEND = enum.auto()
    DEPEND = enum.auto()
    RDEPEND = enum.auto()
    PDEPEND = enum.auto()


Edge = typing.Tuple[str, str]
EdgeKey = typing.Tuple[DepType, int]
CycleTuple = typing.Tuple[typing.List[Edge], Edge]
CycleObserver = typing.Callable[[CycleTuple], None]


class EdgeKeyGetter(object):
    def __init__(self,
                 graph: nx.DiGraph
                 ) -> None:
        self.graph = graph

    def __call__(self,
                 edge: Edge
                 ) -> EdgeKey:
        u, v = edge
        attr = self.graph[u][v]
        return attr['dep'], attr['level']


def get_ordered_nodes(graph: nx.DiGraph,
                      cycle_observer: typing.Optional[CycleObserver] = None
                      ) -> typing.Iterator[str]:
    """
    Get ordered list of packages from dependency graph

    Attempt to get DFS ordered list of dependencies from dependency
    graph `graph`.

    `cycle_observer` is a callback for debugging.  It is called every
    time a cycle is about to be eliminated, and passed a tuple
    with the cycle and the edge being eliminated.
    """

    try:
        while True:
            cycle = nx.find_cycle(graph)
            # resolve the cycle by eliminating the weakest edge
            weakest_edge = max(cycle, key=EdgeKeyGetter(graph))
            if cycle_observer:
                cycle_observer((cycle, weakest_edge))
            graph.remove_edge(*weakest_edge)
    except nx.NetworkXNoCycle:
        pass

    return nx.dfs_postorder_nodes(graph)
