
Dynamic Runtime Customization
=============================

.. note::   Currently this feature only works with dcoker-based backends.

This feature enables early preparation of Lithops workers with the map function and custom Lithops 
runtime already deployed, and ready to be used in consequent computations. This can reduce overall map/reduce 
computation latency significantly, especially when the computation overhead (pickle stage) is longer compared to 
the actual computation performed at the workers.

.. warning::  To protect your privacy, use a private docker registry instead of public docker hub.

To activate this mode, set to True the ``customized_runtime`` property under ``lithops`` section of the config file.

.. code:: yaml

    lithops:
       customized_runtime: True
