"""Peer resolution helpers.

Telethon treats a *string* such as "-1001234567890" as a phone number, so channel
IDs typed into the panel must be converted to int. After a restart a fresh
StringSession also has an empty entity cache, so on a miss we load the dialogs
once and retry.
"""
from __future__ import annotations

import re

_NUM = re.compile(r'^-?\d+$')
_TME = re.compile(r'^(?:https?://)?(?:t|telegram)\.me/', re.I)


def normalize_peer(value):
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if _NUM.match(s):
        return int(s)
    return _TME.sub('', s)


async def resolve_peer(client, value):
    target = normalize_peer(value)
    try:
        return await client.get_input_entity(target)
    except ValueError:
        await client.get_dialogs()
        return await client.get_input_entity(target)
