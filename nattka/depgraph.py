# (c) 2020 Michał Górny
# 2-clause BSD license

"""Dependency graph support"""

import enum
import typing

import networkx as nx
import pkgcore.ebuild.atom
import pkgcore.ebuild.ebuild_src
import pkgcore.restrictions.restriction


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


def traverse_dependencies(dep: pkgcore.restrictions.restriction.base,
                          level: int = 0
                          ) -> typing.Iterator[typing.Tuple[str, int]]:
    """
    Traverse over all dependencies of the package recursively

    Return an iterator over dependency package keys and levels.
    """

    for x in dep:
        if isinstance(x, pkgcore.ebuild.atom.atom):
            yield x.key, level
        else:
            for y, l in traverse_dependencies(x, level + 1):
                yield y, l


def get_depgraph_for_packages(pkgs: typing.Iterable[
                              pkgcore.ebuild.ebuild_src.package]
                              ) -> nx.DiGraph:
    """
    Get DiGraph for packages from `pkgs`
    """

    graph = nx.DiGraph()

    # add nodes for all package keys
    graph.add_nodes_from(x.key for x in pkgs)

    # connect nodes via dependencies
    for pkg in pkgs:
        for deptype in DepType:
            deps = getattr(pkg, deptype.name.lower())
            for dep, level in traverse_dependencies(deps):
                if dep not in graph.nodes():
                    continue
                existing = graph.get_edge_data(pkg.key, dep)
                if (existing is None
                        or (deptype, level) < (existing['dep'],
                                               existing['level'])):
                    graph.add_edge(pkg.key, dep, dep=deptype, level=level)

    return graph
