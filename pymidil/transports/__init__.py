"""Transports — one subpackage per transport (SQS, Redis, webhook, WebSocket).

Each transport package quarantines its wire shapes and exposes its roles:
producers, consumers, and their configs. Named *transports* (the MassTransit/
NServiceBus/Kombu vocabulary, and this codebase's own ubiquitous word) rather
than *brokers*, because push ingress (webhook, WebSocket) is a transport but
not a broker.
"""
