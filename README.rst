memgraphinator
==============

I want a tool to draw the memory usage graph of a given process over time.
I want to *see* memory leaks.

I couldn't find one so I started writing my own.

.. image:: docs/memgraphinator.png

Currently it shows the memory usage for the last 30 seconds.  Resize the window
to see more or less.

Usage::

    ./memgraphinator.py [pid]


Requirements
------------

- Python

- PyGObject with GIR libraries for Gtk etc.

- Linux (for /proc/{pid}/status)


Future plans
------------

- Show current and peak memory usage numbers below the graph
- Show process name and command-line arguments above the graph
- Changeable zoom level (1px = 0.1s, 1s, 10s, entire graph)
- Searching/filtering in the process picker
- Ability to watch multiple processes simultaneously
