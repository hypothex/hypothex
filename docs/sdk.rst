Python SDK
==========

For provider publishing, verified downloads and sharing links, see
:doc:`sharing` and the ``hypothex.sharing`` API. Logged run artifact paths
remain separate from remote publication references.

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

API cost shortcut
-----------------

``run.log_cost`` records the same usage row as ``run.log_usage``::

   import hypothex as hx
   hx.current().log_cost(0.0131, tokens_in=4410, tokens_out=512, example_id="ex-1")

Costs and token counts must be finite and nonnegative. The cost is included in
``cost.api_usd`` when the run ends. Outside a Hypothex run the call is a no-op.
