vdr-pyfe - an alternative vdr-xineliboutput-client
--------------------------------------------------

The goal is to have an independent, alternative but yet complete
implementation of a vdr-xinelibout-client which
works on a PC or Raspberry Pi.

At least the network-code and the multimedia-part will be separated
in a way that other player-platforms can be easily integrated.

Here is how to use the current proof of concept:

On one terminal run ``vdr-pyfe`` to get the data-stream-command

.. code-block::

 $ ./vdr-pyfe.py <hostname>
 client-id 0
 ./vdr-data-socket.py "DATA 0 0xc0a80179:38250 192.168.1.121"
 <waits of input>

then on a second terminal run the line printed above

.. code-block::

 $  ./vdr-data-socket.py "DATA 0 0xc0a80179:38250 192.168.1.121" | cvlc -
 <output>

or

.. code-block::

 $  ./vdr-data-socket.py "DATA 0 0xc0a80179:38250 192.168.1.121" | mplayer -cache 512 -
 <output>

Once the ``vdr-data-socket``-program is running, press enter on the pyfe-terminal.

This works with one channel/recording running. Changing the state of the stream
or activating the OSD will make it crash. For the moment!