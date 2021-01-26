# (C) Datadog, Inc. 2019-present
# All rights reserved
# Licensed under a 3-clause BSD style license (see LICENSE)
import logging
import socket
import time
from itertools import chain

import pytz

try:
    import datadog_agent
except ImportError:
    from ....stubs import datadog_agent

LOGGER = logging.getLogger(__file__)

# AgentCheck methods to transformer name e.g. set_metadata -> metadata
SUBMISSION_METHODS = {
    'gauge': 'gauge',
    'count': 'count',
    'monotonic_count': 'monotonic_count',
    'rate': 'rate',
    'histogram': 'histogram',
    'historate': 'historate',
    'set_metadata': 'metadata',
    # These submission methods require more configuration than just a name
    # and a value and therefore must be defined as a custom transformer.
    'service_check': '__service_check',
}


def create_submission_transformer(submit_method):
    # During the compilation phase every transformer will have access to all the others and may be
    # passed the first arguments (e.g. name) that will be forwarded the actual AgentCheck methods.
    def get_transformer(_transformers, *creation_args, **modifiers):
        # The first argument of every transformer is a map of named references to collected values.
        def transformer(_sources, *call_args, **kwargs):
            kwargs.update(modifiers)

            # TODO: When Python 2 goes away simply do:
            # submit_method(*creation_args, *call_args, **kwargs)
            submit_method(*chain(creation_args, call_args), **kwargs)

        return transformer

    return get_transformer


def create_extra_transformer(column_transformer, source=None):
    # Every column transformer expects a value to be given but in the post-processing
    # phase the values are determined by references, so to avoid redefining every
    # transformer we just map the proper source to the value.
    if source:

        def transformer(sources, **kwargs):
            return column_transformer(sources, sources[source], **kwargs)

    # Extra transformers that call regular transformers will want to pass values directly.
    else:

        transformer = column_transformer

    return transformer


def normalize_datetime(dt):
    # Prevent naive datetime objects
    if dt.tzinfo is None:
        # The stdlib datetime.timezone.utc doesn't work properly on Windows
        dt = dt.replace(tzinfo=pytz.utc)

    return dt


class ConstantRateLimiter:
    def __init__(self, rate_limit_s):
        """
        :param rate_limit_s: rate limit in seconds
        """
        self.rate_limit_s = rate_limit_s
        self.period_s = 1 / rate_limit_s if rate_limit_s > 0 else 0
        self.last_event = 0

    def sleep(self):
        """
        Sleeps long enough to enforce the rate limit
        """
        elapsed_s = time.time() - self.last_event
        sleep_amount = max(self.period_s - elapsed_s, 0)
        time.sleep(sleep_amount)
        self.last_event = time.time()


def resolve_db_host(host):
    agent_hostname = datadog_agent.get_hostname()
    if not host or host in {'localhost', '127.0.0.1'}:
        return agent_hostname
    try:
        host_ip = socket.gethostbyname(host)
        if host_ip == socket.gethostbyname(agent_hostname):
            # it's an alias to the agent host, so best returned the agent host as detected by the datadog_agent
            # as that is more likely to match the true agent host and therefore inherit the correct metadata
            return agent_hostname
        # agent is talking to an external database host
        return host
    except socket.gaierror:
        # unix domain socket or an invalid hostname
        LOGGER.debug("failed to resolve DB host: %s. falling back to agent hostname: %s", host, agent_hostname)
        return agent_hostname
