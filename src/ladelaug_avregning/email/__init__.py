"""Outgoing email (Epic 10).

``sender.build_sender(config)`` returns an ``EmailSender`` for the configured
backend; ``domain.notifications.NotificationRepo`` queues messages and drains the
queue with retry/backoff.
"""

from ladelaug_avregning.email.sender import EmailSender, build_sender

__all__ = ["EmailSender", "build_sender"]
