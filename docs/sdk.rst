Python SDK
==========

.. code-block:: python

   import hypothex as hx

   run = hx.current()   # no-op outside Hypothex
   run.log({"loss": 0.41})
   run.log_predictions([{"id": "ex-1", "prediction": 1}])
   run.log_artifact("model.pt", kind="checkpoint")

.. automodule:: hypothex.sdk
   :members:

Metric functions
----------------

.. automodule:: hypothex.metrics
   :members:
