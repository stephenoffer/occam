"""Text messages to patients.

Messages are queued in the ``messages`` table; the SMS gateway's sender service picks up
unsent rows and marks them sent. Nothing here talks to the gateway.
"""
