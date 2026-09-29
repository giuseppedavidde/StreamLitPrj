"""Regression tests for the multi-leg builder state handling (offline, no AI).

``streamlit.testing.v1.AppTest`` **cannot** simulate a ``st.data_editor`` edit:
the data editor is exposed as a plain ``Dataframe`` node (no ``set_value``, no
widget-state replay), so the "edit a cell and check it survives the next rerun"
flow cannot be driven end-to-end through AppTest. That limitation is documented
here and worked around with the two things that actually caused the reported
bug:

1. ``apply_editor_state`` — the pure state-resolution/merge logic extracted from
   ``render_leg_builder`` (unit-tested directly);
2. the widget-identity invariant that makes the *first* edit stick — the
   ``data`` argument handed to ``st.data_editor`` must stay constant across
   reruns, because with ``num_rows="dynamic"`` Streamlit includes the data in
   the widget identity. Feeding the editor's own output back as ``data``
   (the legacy pattern, also covered below) changes the element id on the next
   rerun and orphans the pending edit.
"""

# pylint: disable=wrong-import-position

from __future__ import annotations

from pathlib import Path
import sys

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import (  # noqa: E402
    DEMO_LEGS,
    LEGS_BASE_KEY,
    LEGS_EDITOR_KEY,
    apply_editor_state,
    parse_legs,
)
from models import Direction, OptionKind  # noqa: E402

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"

# A pending edit as Streamlit stores it under the data_editor widget key.
PENDING_EDIT = {
    "edited_rows": {
        0: {"Tipo": "put", "Direzione": "short", "Strike": 55.0,
            "Premio": 7.5, "IV": 0.42},
        1: {"Premio": 3.25},
    },
    "added_rows": [],
    "deleted_rows": [],
}

# Legacy (buggy) pattern: the editor output is written back into the same state
# that is passed as ``data``, so the data argument changes on the next rerun.
LEGACY_SCRIPT = """
import pandas as pd
import streamlit as st

DEMO = pd.DataFrame(
    [
        {"Tipo": "call", "Direzione": "long", "Strike": 59.0, "Premio": 10.71},
        {"Tipo": "call", "Direzione": "short", "Strike": 70.0, "Premio": 4.96},
    ]
)
if "legs_df" not in st.session_state:
    st.session_state["legs_df"] = DEMO.copy()

edited = st.data_editor(
    st.session_state["legs_df"], num_rows="dynamic", key="legs_editor"
)
st.session_state["legs_df"] = edited
"""


def _editor_node(app: AppTest):
    """Return the multi-leg data_editor node (there are other dataframes around)."""
    nodes = [node for node in app.get("dataframe") if node.key == LEGS_EDITOR_KEY]
    assert len(nodes) == 1
    return nodes[0]


def _editor_id(app: AppTest) -> str:
    return _editor_node(app).proto.id


def _legs_echo_table(app: AppTest):
    """The app's parsed-legs echo table (``leg_echo_table``), i.e. what got computed.

    ``_editor_node(app).value`` is the *pre-edit* base (Streamlit serializes the
    arrow payload before applying edits), so the echo table is the observable
    end-to-end result of ``data_editor`` → ``parse_legs`` → ``Position``.
    """
    for node in app.get("dataframe"):
        if "Contratti" in list(node.value.columns):
            return node.value
    raise AssertionError("legs echo table not rendered")


# ── pure merge/persistence logic ─────────────────────────────────────────
def test_apply_editor_state_applies_cell_edits_without_touching_base():
    """First-edit persistence: pending edits apply and the base stays pristine."""
    base = DEMO_LEGS.copy()
    effective = apply_editor_state(base, PENDING_EDIT)

    assert effective.iloc[0]["Premio"] == 7.5
    assert effective.iloc[1]["Premio"] == 3.25
    assert effective.iloc[0]["Strike"] == 55.0
    assert base.equals(DEMO_LEGS)  # the base is never mutated


def test_apply_editor_state_handles_selectbox_columns():
    """Tipo / Direzione / Scadenza edits must behave like numeric ones."""
    effective = apply_editor_state(DEMO_LEGS.copy(), PENDING_EDIT)
    legs = parse_legs(effective)

    assert legs[0].kind is OptionKind.PUT
    assert legs[0].direction is Direction.SHORT
    assert legs[0].strike == 55.0
    assert legs[0].entry_premium == 7.5
    assert legs[0].iv == 0.42


def test_apply_editor_state_adds_and_deletes_dynamic_rows():
    """``num_rows="dynamic"``: added rows append, deleted rows drop by position."""
    state = {
        "edited_rows": {},
        "added_rows": [dict(DEMO_LEGS.iloc[1])],
        "deleted_rows": [0],
    }
    effective = apply_editor_state(DEMO_LEGS.copy(), state)

    assert len(effective) == 2
    assert effective.iloc[0]["Strike"] == 70.0  # row 0 was deleted
    assert effective.iloc[1]["Strike"] == 70.0  # the added leg
    assert list(effective.index) == [0, 1]


def test_apply_editor_state_tolerates_missing_or_malformed_state():
    """No session state yet, or out-of-range positions, must not raise."""
    for state in (None, {}, "garbage", {"edited_rows": {9: {"Premio": 1.0}}}):
        effective = apply_editor_state(DEMO_LEGS.copy(), state)
        assert effective.reset_index(drop=True).equals(DEMO_LEGS.reset_index(drop=True))


# ── widget identity invariant (AppTest) ──────────────────────────────────
def test_legs_base_is_stable_across_reruns_with_pending_edit():
    """The ``data`` argument must not change while an edit is pending.

    With ``num_rows="dynamic"`` the element id is derived from the data, so a
    changing ``data`` argument orphans the pending edit. The base table must
    stay identical across reruns (this is what makes the first edit stick).
    """
    app = AppTest.from_file(str(APP_PATH)).run()
    first_id = _editor_id(app)
    assert app.session_state[LEGS_BASE_KEY].equals(DEMO_LEGS)

    app.session_state[LEGS_EDITOR_KEY] = PENDING_EDIT
    app.run()
    # the real backend merge (base + pending state) already flows into the parsed
    # legs in the same run: no second attempt is needed for the value to stick
    echo = _legs_echo_table(app)
    assert echo["Premio"].tolist() == [7.5, 3.25]
    assert echo["Strike"].tolist() == [55.0, 70.0]
    assert echo["Tipo"].tolist() == ["put", "call"]
    assert _editor_id(app) == first_id
    assert app.session_state[LEGS_BASE_KEY].equals(DEMO_LEGS)  # not polluted

    app.run()
    assert _editor_id(app) == first_id
    assert not app.exception


def test_legacy_feedback_pattern_churns_the_editor_identity():
    """The old anti-pattern changes the element id right after an edit.

    This is the root cause of "type it twice": the pending edit is submitted
    under an element id that no longer exists after the rerun.
    """
    app = AppTest.from_string(LEGACY_SCRIPT).run()
    first_id = _editor_id(app)

    legacy_edit = {"edited_rows": {0: {"Premio": 7.5}}, "added_rows": [], "deleted_rows": []}
    app.session_state[LEGS_EDITOR_KEY] = legacy_edit
    app.run()  # edit applied, then folded back into the ``data`` argument
    app.run()  # data changed → new element id

    assert _editor_id(app) != first_id


def test_preset_button_restores_the_demo_table_and_clears_pending_edits():
    """Preset must reset both the base table and the widget state."""
    app = AppTest.from_file(str(APP_PATH)).run()
    app.session_state[LEGS_EDITOR_KEY] = PENDING_EDIT
    app.run()

    preset = next(b for b in app.button if b.label == "Preset DRAM 59/70")
    preset.click().run()

    assert not app.exception
    assert app.session_state[LEGS_BASE_KEY].equals(DEMO_LEGS)
    assert app.session_state[LEGS_EDITOR_KEY] == {
        "edited_rows": {}, "added_rows": [], "deleted_rows": [],
    }
    assert _legs_echo_table(app)["Premio"].tolist() == DEMO_LEGS["Premio"].tolist()


def test_prefill_button_is_disabled_without_market_data():
    """``Precompila dal mid`` stays disabled (no spot) and never hits the network."""
    app = AppTest.from_file(str(APP_PATH)).run()

    prefill = next(b for b in app.button if b.label == "Precompila dal mid")
    assert prefill.disabled is True
    assert not app.exception
