from time import sleep
from turtle import ScrolledCanvas

from numpy import true_divide


class Edge:
    def __init__(self, src, dest, weight):
        self.src = src
        self.dest = dest
        self.weight = weight

    def __eq__(self, other):
        return (self.src == other.src and self.dest == other.dest) or (
            self.src == other.dest and self.dest == other.src
        )

    def __hash__(self):
        return hash(self.src.title) + hash(self.dest.title)

    def is_cyclic(self):
        return self.src.title == self.dest.title

    def either_title_startswith(self, str):
        return self.src.title.startswith(str) or self.dest.title.startswith(str)

    # see if either the source or destination node's summary is in the list of summaries
    def either_summary_in(self, summaries, threshold):
        sleep(0.05)
        return (
            self.src.summary[:threshold] in summaries
            or self.dest.summary[:threshold] in summaries
        )

    # fix edges so that they connect to graph again in case of consolidation of nodes
    def consolidate(self, other):
        other_src = other.src.title.lower().strip()
        other_dest = other.dest.title.lower().strip()
        this_src = self.src.title.lower().strip()
        this_dest = self.dest.title.lower().strip()
        if this_src in other_src:
            return {Edge(self.src, other.dest, other.weight), self}
        elif other_src in this_src:
            return {Edge(other.src, self.dest, self.weight), other}
        elif this_src in other_dest:
            return {Edge(other.src, self.src, other.weight), self}
        elif other_dest in this_src:
            return {Edge(other.dest, self.dest, self.weight), other}
        elif this_dest in other_dest:
            return {Edge(other.src, self.dest, other.weight), self}
        elif other_dest in this_dest:
            return {Edge(self.src, other.dest, self.weight), other}
        elif this_dest in other_src:
            return {Edge(self.dest, other.dest, other.weight), self}
        elif other_src in this_dest:
            return {Edge(self.src, other.dest, self.weight), other}
        else:
            return {self, other}

    # see if any of the titles can be consolitdated
    def can_be_consolidated(this_titles, other_titles):
        for title_t in this_titles:
            for title_o in other_titles:
                if title_t in title_o or title_o in title_t:
                    return True
        return False
