"""One PNG per process; exiting returns plotting memory to the operating system."""

import json
import sys

from .analysis import Assessment, Point, timestamp


def main():
    from .plot import draw_chart
    request = json.load(sys.stdin)
    result = request["assessment"]
    points = tuple(Point(timestamp(p["time"]), p["current"], p["baseline"]) for p in result["points"])
    assessment = Assessment(result["status"], result["reason"], points)
    sys.stdout.buffer.write(draw_chart(assessment, demo=request["demo"]))


if __name__ == "__main__":
    main()
