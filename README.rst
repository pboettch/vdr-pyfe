vdr-pyfe - an alternative vdr-xineliboutput-client
--------------------------------------------------

The goal is to have an independent, alternative but yet complete
implementation of a vdr-xinelibout-client which
works on a PC or Raspberry Pi.

At least the network-code and the multimedia-part will be separated
in a way that other player-platforms can be easily integrated.

Here is how to use the current proof of concept.

First of all, vlc has to be installed and the command-line-version (``cvlc``) has to be available in the PATH.

Then simply run

.. code-block::

 $ ./vdr-pyfe.py <hostname>

OSD is data is received, parsed, but not rendered anywhere.

No input has been configured, so channel-changes have to be done via another vdr-..fe-session.