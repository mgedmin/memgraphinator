memgraphinator
==============

I want a tool to draw the memory usage graph of a given process over time.
I want to *see* memory leaks.

I couldn't find one so I started writing my own.

.. image:: docs/memgraphinator.png

Currently it shows the memory usage for the last 30 seconds.  Resize the window
to see more or less.

Usage::

    ./memgraphinator.py [--exit-when-process-dies]
    ./memgraphinator.py [--exit-when-process-dies] [-p|--pid] PID
    ./memgraphinator.py [--exit-when-process-dies] [--] command [args ...]
    ./memgraphinator.py -h|--help


Graph process memory usage

positional arguments:
  command [args]        Command to execute and monitor

optional arguments:
  -h, --help            Show this help message and exit
  -p PID, --pid PID     Specify existing process to monitor
  --exit-when-process-dies
                        Exit when monitored process dies


Requirements
------------

- Python

- PyGObject with GIR libraries for Gtk etc.

- Linux (for /proc/{pid}/status)


Future plans
------------

- Show memory usage number somewhere
- Changeable zoom level (1px = 0.1s, 1s, 10s, entire graph)
- Ability to watch multiple processes simultaneously
