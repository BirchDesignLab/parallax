"""Seat factories, registered by adapters and scripted test fixtures."""
from __future__ import annotations

from collections.abc import Callable

from parallax.config import Config, ConfigError, SeatConfig
from parallax.seats.base import Seat

ADAPTERS: dict[str, Callable[[SeatConfig, Config], Seat]] = {}


def make_seats(cfg: Config) -> dict[str, Seat]:
    # Check all names before constructing seats so a typo cannot partly build a pair.
    for seat_cfg in cfg.seats:
        if seat_cfg.adapter not in ADAPTERS:
            raise ConfigError(f"seats.{seat_cfg.name}.adapter: unknown adapter {seat_cfg.adapter!r}")
    return {seat_cfg.name: ADAPTERS[seat_cfg.adapter](seat_cfg, cfg) for seat_cfg in cfg.seats}


from parallax.seats.claude import ClaudeSeat
from parallax.seats.codex import CodexSeat

ADAPTERS["claude"] = lambda seat, cfg: ClaudeSeat(seat, cfg)
ADAPTERS["codex"] = lambda seat, cfg: CodexSeat(seat, cfg)
