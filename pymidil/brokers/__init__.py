"""Broker transports — one subpackage per broker (SQS, …).

Each broker package quarantines its wire shapes and exposes the standard
trio: a producer, a consumer, and their configs.
"""
