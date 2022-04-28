#   Copyright 2020-present Michael Hall
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

from __future__ import annotations

"""
Dice parsing.

Must hold up to adversarial inputs.

Does not support exploding dice.

Logic here is contained to a seperate file intentionally.
"""
import operator
import random
import re
import sys
from typing import Any, Callable, TypeVar

import numpy as np

try:
    from numba import njit, prange
except ImportError:
    numba = None

    import warnings as _wrn

    _wrn.warn("Unable to import numba, falling back to non-JIT")

    T = TypeVar("T")

    def njit(*args: Any, **kwargs: Any) -> Callable[[T], T]:
        return lambda f: f

    prange = range


__all__ = ["Expression", "DiceError"]

_USE_P = sys.maxsize > 2**32

_OP_T = TypeVar("_OP_T")

OperatorType = Callable[[_OP_T, _OP_T], _OP_T]

OPS: dict[str, OperatorType] = {
    "+": operator.add,
    "-": operator.sub,
}

ROPS: dict[OperatorType, str] = {
    operator.add: "+",
    operator.sub: "-",
}

DIE_COMPONENT_RE = re.compile(
    # 2 digit quantities of dice, and maximum 100 sides
    r"^(?P<QUANT>[1-9][0-9]?)d(?P<SIDES>(?:100)|(?:[1-9][0-9]?))"  # #d#
    r"(?:(?P<KD>[v\^])(?P<KDQUANT>[1-9][0-9]{0,2}))?"  # (optional) v# or ^#
)


class DiceError(Exception):
    def __init__(self, msg=None, *args: Any):
        self.msg = msg
        super().__init__(msg, *args)


@njit("uint32(uint32, uint32)", nogil=True)
def ncr(n: int, r: int) -> int:
    # With numba, this is significantly better than using scipy.special.comb
    # https://en.wikipedia.org/wiki/Binomial_coefficient#Multiplicative_formula
    if 0 <= r <= n:
        ntok = 1
        rtok = 1
        # Branchless handling of `if n - r < r then r = n - r`
        # numba is smart enough to not recompute the condition
        # but uses better instructions when provided it this way.
        # This is a micro optimization, but this entire file is
        # intended to be optimized as much as can be reasonably done.
        r = ((n - r) * (n - r < n)) + (r * (not (n - r < n)))
        for t in prange(r):
            ntok *= n - t
            rtok *= t + 1
        return ntok // rtok
    else:
        return 0


#########################################################################################
# https://en.m.wikipedia.org/wiki/Order_statistic#Dealing_with_discrete_variables       #
#########################################################################################
# Roll X d Y Keep Best/Worst                                                            #
#########################################################################################
# $$\mathbb{E}(\text{Roll } X \text{ d}Y \text{ and keep highest } Z) =                 #
# \sum_{k=0}^{Z-1} \sum_{j=1}^Y j \sum_{l=0}^k                                          #
# \binom{X}{l}\Big(\Big(\frac{Y-j}{Y}\Big)^l\Big(\frac{j}{Y}\Big)^{X-l}                 #
# - \Big(\frac{Y-j+1}{Y}\Big)^l\Big(\frac{j-1}{Y}\Big)^{X-l}\Big)$$                     #
#                                                                                       #
# $$\mathbb{E}(\text{Roll } X \text{ d}Y \text{ and keep lowest } Z) =                  #
# \sum_{k=1}^{Z} \sum_{j=1}^Y j \sum_{l=0}^{X-k}                                        #
# \binom{X}{l}\Big(\Big(\frac{Y-j}{Y}\Big)^l\Big(\frac{j}{Y}\Big)^{X-l}                 #
# - \Big(\frac{Y-j+1}{Y}\Big)^l\Big(\frac{j-1}{Y}\Big)^{X-l}\Big)$$                     #
#                                                                                       #
#########################################################################################
#########################################################################################


@njit("float32(uint32, uint32, uint32, uint32)")
def _inner_flattened_cdf_math(quant: int, sides: int, i: int, j: int) -> float:
    x = (((sides - j) / sides) ** i) * ((j / sides) ** (quant - i))
    y = (((sides - j + 1) / sides) ** i) * (((j - 1) / sides) ** (quant - i))
    return ncr(quant, i) * (x - y)


@njit("float32(uint32, uint32, uint32)", parallel=_USE_P, nogil=True, cache=True)
def _ev_roll_dice_keep_best(quant: int, sides: int, keep: int) -> float:

    outermost_sum = 0
    for k in prange(0, keep):
        middle_sum = 0
        for j in prange(1, sides + 1):
            inner_sum = 0
            for i in prange(0, k + 1):
                inner_sum += _inner_flattened_cdf_math(quant, sides, i, j)
            middle_sum += j * inner_sum
        outermost_sum += middle_sum
    return outermost_sum


@njit("float32(uint32, uint32, uint32)", parallel=_USE_P, nogil=True)
def _ev_roll_dice_keep_worst(quant: int, sides: int, keep: int) -> float:

    outermost_sum = 0
    for k in prange(1, keep + 1):
        middle_sum = 0
        for j in prange(1, sides + 1):
            inner_sum = 0
            for i in prange(0, quant - k + 1):
                inner_sum += _inner_flattened_cdf_math(quant, sides, i, j)
            middle_sum += j * inner_sum
        outermost_sum += middle_sum
    return outermost_sum


@njit("float32(uint32, uint32, uint32, uint32)", nogil=True)
def fast_analytic_ev(quant: int, sides: int, low: int, high: int) -> float:

    if high < quant:
        return _ev_roll_dice_keep_best(quant, sides, high)
    if low:
        return _ev_roll_dice_keep_worst(quant, sides, low)

    return quant * (sides + 1) / 2


@njit("uint32(uint32, uint32, uint32, uint32)")
def fast_roll(quant: int, sides: int, low: int, high: int) -> int:
    c = np.random.randint(1, sides, (quant,))
    c.sort()
    return np.sum(c[low:high])


class NumberofDice:
    def __init__(self, QUANT, SIDES, KD=None, KDQUANT=None):
        self.quant = int(QUANT)
        self.sides = int(SIDES)

        if KD and KDQUANT:
            mod = int(KDQUANT)
            if mod > QUANT:
                raise DiceError("You can't keep more dice than you rolled.")
            self._kd_expr = f"{KD}{KDQUANT}"
            if KD == "v":
                self.keep_low = min(mod, self.quant)
                self.keep_high = self.quant
            else:
                self.keep_high = min(mod, self.quant)
                self.keep_low = 0
        else:
            self.keep_high = self.quant
            self.keep_low = 0
            self._kd_expr = ""

    def __repr__(self):
        return f"<Die: {self}>"

    def __str__(self):
        return f"{self.quant}d{self.sides}{self._kd_expr}"

    @property
    def high(self) -> int:
        quant = (self.keep_low or self.keep_high) if self._kd_expr else self.quant
        return quant * self.sides

    @property
    def low(self) -> int:
        return (self.keep_low or self.keep_high) if self._kd_expr else self.quant

    def get_ev(self) -> float:
        return fast_analytic_ev(self.quant, self.sides, self.keep_low, self.keep_high)

    def verbose_roll(self) -> tuple[int, list[int]]:
        choices = random.choices(range(1, self.sides + 1), k=self.quant)
        if self._kd_expr:
            if self.keep_high < self.quant:
                filtered = sorted(choices, reverse=True)[: self.keep_high]
            else:
                filtered = sorted(choices)[: self.keep_low]
            return sum(filtered), choices
        return sum(choices), choices

    def full_verbose_roll(self) -> tuple[int, str]:
        parts = []
        choices = random.choices(range(1, self.sides + 1), k=self.quant)
        parts.append(f"{self.quant}d{self.sides} ({', '.join(map(str, choices))})")
        if self._kd_expr:
            if self.keep_high < self.quant:
                choices.sort(reverse=True)
                choices = choices[: self.keep_high]
                parts.append(f"-> Highest {self.keep_high} ({', '.join(map(str, choices))})")
            else:
                choices.sort()
                choices = choices[: self.keep_low]
                parts.append(f"-> Lowest {self.keep_low} ({', '.join(map(str, choices))})")

        total = sum(choices)
        parts.append(f"-> ({total})")
        return total, " ".join(parts)

    def roll(self) -> int:
        low, high = 0, self.quant
        if self._kd_expr:
            if self.keep_high < self.quant:
                low = self.quant - self.keep_high
            else:
                high = self.keep_low

        return fast_roll(self.quant, self.sides, low, high)


def _try_die_or_int(expr: str) -> tuple[NumberofDice | int, str]:

    if m := DIE_COMPONENT_RE.search(expr):
        assert m is not None, "mypy#8128"  # nosec
        return NumberofDice(**m.groupdict()), expr[m.end() :]

    if m := re.search(r"^[1-9][0-9]{0,2}", expr):
        assert m is not None, "mypy#8128"  # nosec
        return int(m.group()), expr[m.end() :]

    raise DiceError()


class Expression:
    def __init__(self):
        self._components = []
        self._current_num_dice = 0

    def __repr__(self):
        if self._components:
            return "<Dice Expression '%s'>" % " ".join(ROPS.get(c, str(c)) for c in self._components)

        else:
            return "<Empty Dice Expression>"

    def __str__(self):
        return " ".join(ROPS.get(c, str(c)) for c in self._components)

    def add_dice(self, die: NumberofDice | int):
        if len(self._components) % 2:
            raise DiceError(f"Expected an operator next (Current: {self})")

        if isinstance(die, NumberofDice):
            n = self._current_num_dice + die.quant
            if n > 1000:
                raise DiceError("Whoops, too many dice here")
            self._current_num_dice = n

        self._components.append(die)

    def add_operator(self, op: OperatorType):
        if not len(self._components) % 2:
            raise DiceError(f"Expected a number or die next (Current: {self}")

        self._components.append(op)

    @staticmethod
    def _group_by_dice(components: list):

        start = 0
        for idx, component in enumerate(components):
            if isinstance(component, NumberofDice):
                if start != idx:
                    yield components[start:idx]
                start = idx
        else:
            yield components[start:]

    def verbose_roll2(self):
        total = 0
        parts = []
        next_operator = operator.add

        for group in self._group_by_dice(self._components):
            partial_total = 0
            partial_parts = []
            dice_part = ""
            op_last = False
            last_op = None

            for component in group:
                if isinstance(component, int):
                    total = next_operator(total, component)
                    partial_total = next_operator(partial_total, component)
                    partial_parts.append(f"{component}")
                    op_last = False
                elif isinstance(component, NumberofDice):
                    amount, verbose_result = component.verbose_roll()
                    total = next_operator(total, amount)
                    partial_total = next_operator(partial_total, amount)
                    partial_parts.append(f"{component}")
                    dice_part = f": {verbose_result} -> {amount}"
                    op_last = False
                else:
                    next_operator = component
                    partial_parts.append(f"{ROPS[next_operator]}")
                    op_last = True

            total += partial_total

            if op_last:
                last_op = partial_parts.pop()

            st = " ".join(partial_parts).strip()
            if dice_part:
                ex = " ".join(partial_parts[1:]).strip()
                parts.append(f"{st}{dice_part} {ex} ({partial_total})")
            else:
                parts.append(f"{st} ({partial_total})")

            if last_op:
                parts.append(last_op)

        return "\n".join(parts).strip()

    def verbose_roll(self):
        total = 0
        parts = []
        next_operator = operator.add

        partial_total = 0

        for component in self._components:
            if isinstance(component, int):
                total = next_operator(total, component)
                partial_total = next_operator(partial_total, component)
                parts.append(f"{component}")
            elif isinstance(component, NumberofDice):
                if parts:
                    parts.pop()
                if partial_total:
                    parts.append(f"({partial_total})")
                    partial_total = 0

                amount, verbose_result = component.verbose_roll()
                total = next_operator(total, amount)
                partial_total = next_operator(partial_total, amount)
                parts.append(f"\n{component}: {verbose_result} -> {amount}")
            else:
                next_operator = component
                parts.append(f"{ROPS[next_operator]}")
        else:
            if partial_total:
                parts.append(f"({partial_total})")

        return total, " ".join(parts).strip()

    def full_verbose_roll(self):
        if not len(self._components) % 2:
            raise DiceError(f"Incomplete Expression: {self}")

        total = 0
        parts = []
        next_operator = operator.add

        for component in self._components:
            if isinstance(component, int):
                total = next_operator(total, component)
                parts.append(f"{component}")
            elif isinstance(component, NumberofDice):
                amount, verbose_result = component.full_verbose_roll()
                total = next_operator(total, amount)
                parts.append(verbose_result)
            else:
                next_operator = component
                parts.append(f"\n{ROPS[next_operator]} ")

        parts.append(f"\n-------------\n= {total}")

        return total, "".join(parts)

    def roll(self) -> int:
        if not len(self._components) % 2:
            raise DiceError(f"Incomplete Expression: {self}")
        total = 0
        next_operator = operator.add

        for component in self._components:
            if isinstance(component, int):
                total = next_operator(total, component)
            elif isinstance(component, NumberofDice):
                total = next_operator(total, component.roll())
            else:
                next_operator = component

        return total

    def get_min(self):
        if not len(self._components) % 2:
            raise DiceError(f"Incomplete Expression: {self}")
        total = 0
        next_operator = operator.add

        for component in self._components:
            if isinstance(component, int):
                total = next_operator(total, component)
            elif isinstance(component, NumberofDice):
                mod = component.high if next_operator is operator.sub else component.low
                total = next_operator(total, mod)
            else:
                next_operator = component

        return total

    def get_max(self):
        if not len(self._components) % 2:
            raise DiceError(f"Incomplete Expression: {self}")
        total = 0
        next_operator = operator.add

        for component in self._components:
            if isinstance(component, int):
                total = next_operator(total, component)
            elif isinstance(component, NumberofDice):
                mod = component.low if next_operator is operator.sub else component.high
                total = next_operator(total, mod)
            else:
                next_operator = component

        return total

    @classmethod
    def from_str(cls, expr: str):

        c = 0
        obj = cls()

        while expr := expr.strip():

            if c % 2:

                if op := OPS.get(expr[0], None):
                    assert op is not None, "mypy#8128"  # nosec
                    obj.add_operator(op)
                    expr = expr[1:]
                else:
                    raise DiceError(f"Incomplete Expression: {obj}")

            else:
                part, expr = _try_die_or_int(expr)
                obj.add_dice(part)

            c += 1

        if not (c % 2 or c):
            raise DiceError(f"Incomplete Expression: {obj}")

        expr = expr.strip()

        return obj

    def get_ev(self) -> float:
        if not len(self._components) % 2:
            raise DiceError(f"Incomplete Expression: {self}")

        total = 0
        next_operator = operator.add

        # Taking a shortcut here. it's "correct enough"
        for component in self._components:
            if isinstance(component, int):
                total = next_operator(total, component)
            elif isinstance(component, NumberofDice):
                total = next_operator(total, component.get_ev())
            else:
                next_operator = component

        return total
