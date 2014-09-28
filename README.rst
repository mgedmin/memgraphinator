memgraphinator
==============

I want a tool to draw the memory usage graph of a given process over time.
I want to *see* memory leaks.

I couldn't find one so I started writing my own.

.. image:: docs/memgraphinator.png


Usage
-----

::

    ./memgraphinator.py [--exit-when-process-dies]
    ./memgraphinator.py [--exit-when-process-dies] [-p|--pid] PID ...
    ./memgraphinator.py [--exit-when-process-dies] [--] command [args ...]
    ./memgraphinator.py -h|--help

positional arguments:
  command [args]        Command to execute and monitor

optional arguments:
  -h, --help            Show this help message and exit
  -p PID, --pid PID     Specify existing process to monitor
  --exit-when-process-dies
                        Exit when monitored process dies


Requirements
------------

- Linux (for /proc/{pid}/status)

- Python

- PyGObject with GIR libraries for Gtk etc.

- A reasonably new Gtk+ (with header bars etc., which I think means 3.12)

.. note:: Ubuntu 14.04 LTS is too old, unless you enable the unstable
          `GNOME 3 staging PPA`_.

.. _GNOME 3 staging PPA: https://launchpad.net/~gnome3-team/+archive/ubuntu/gnome3-staging


Future plans
------------

- Option to see RSS instead of VIRT
- Accurate time axis (when you suspend laptop, graph stops, but this is
  not refected in "N seconds ago" messages)
- More efficient drawing when zoomed out (plotting every single point for 2
  hours makes my CPU hurt)
- Export graph to CSV
