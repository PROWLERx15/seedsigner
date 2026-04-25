# Running Tests

The tests are designed to be run on non-Raspi hardware.

On your testing machine you'll have to install:
```bash
# general dependencies
pip3 install -r requirements.txt

# test suite dependencies
pip3 install -r tests/requirements.txt
```

Then make the `seedsigner` python module visible/importable to the tests by installing it:
```
pip3 install -e .
```

Run the whole test suite:
```
pytest
```

Run a specific test file:
```
pytest tests/test_this_file.py
```

Run a specific test:
```
pytest tests/test_this_file.py::test_this_specific_test
```

Force pytest to show logging output:
```bash
pytest tests/test_this_file.py::test_this_specific_test -o log_cli=1

# or (same result)

pytest tests/test_this_file.py::test_this_specific_test --log-cli-level=DEBUG
```

Annoying complications:
* If you want to see `print()` statements that are in a test file, add `-s`
* Better idea: use a proper logger in the test file and use one of the above options to display logs


### Test Coverage
Run tests and generate test coverage
```
coverage run -m pytest
```

Show the resulting test coverage details:
```
coverage report
```

Generate the html overview:
```
coverage html
```

---

## How FlowTests Work

SeedSigner's UI is a state machine: each screen is a `View` class whose
`run()` method returns a `Destination(NextView)` to tell the Controller
where to go next. A **FlowTest** simulates a user clicking through
those screens by feeding a list of `FlowStep` events into a stub
Controller and asserting the View transitions match what was expected.

The framework lives in [`tests/base.py`](base.py); the test files
(`test_flows_*.py`) build on it.

### The `FlowStep` dataclass

```python
@dataclass
class FlowStep:
    expected_view: type[View] = None        # which View should be active right now
    before_run: Callable[[View], None] = None  # mutate state before run() executes
    screen_return_value: int | str = None   # mock the Screen's return value
    button_data_selection: str | tuple = None  # mock a button press, matched by label
    is_redirect: bool = False               # this step is a redirect, not a render
```

Each step says "we expect to be on `expected_view`; here's how I want to
interact with it; the framework should then route to the next View."

### The four fields in plain language

- **`expected_view`** — The View class the framework should currently be
  on. If the actual View is anything else, the test fails. This is the
  assertion at the heart of every step.

- **`button_data_selection`** — Used when the View renders a button list
  and you want to click one. Pass the same string/tuple constant defined
  on the View class (e.g. `MainMenuView.SCAN`). The framework finds that
  entry in the View's `button_data` list and feeds back its index, so
  the View's `run()` method can branch into the matching `if/elif` arm.

- **`before_run`** — A function that runs *before* the View's `run()` is
  called. Use this to inject state the View depends on — load a seed
  into the decoder, set a controller flag, prime the storage. Without it
  many flows can't reach the next step.

- **`is_redirect`** — Some Views never render. They check a condition in
  `__post_init__()` and call `self.set_redirect(Destination(...))` to
  forward immediately. Mark these steps `is_redirect=True` so the test
  framework knows to expect a forward without a screen render.

### A real example, annotated

This is `test_scan_psbt_first_then_correct_seedqr_flow` from
[`test_flows_psbt.py`](test_flows_psbt.py), with comments on what each
field is doing.

```python
def test_scan_psbt_first_then_correct_seedqr_flow(self):
    # before_run helpers — inject the PSBT and the seed into the QR
    # decoder so the ScanView "sees" valid data when run() executes.
    def load_psbt_into_decoder(view: scan_views.ScanView):
        view.decoder.add_data("cHNidP8BAN…")  # base64 PSBT bytes

    def load_seed_into_decoder(view: scan_views.ScanView):
        view.decoder.add_data("080115060387…")  # SeedQR digits

    self.run_sequence([
        # Start on Main Menu, click "Scan".
        FlowStep(
            MainMenuView,
            button_data_selection=MainMenuView.SCAN,
        ),

        # Now on ScanView. Use before_run to feed it a PSBT before
        # run() executes, so it decodes a real transaction.
        FlowStep(
            scan_views.ScanView,
            before_run=load_psbt_into_decoder,
        ),

        # PSBT detected, no seed loaded yet — landed on
        # PSBTSelectSeedView. Click "Scan Seed".
        FlowStep(
            psbt_views.PSBTSelectSeedView,
            button_data_selection=psbt_views.PSBTSelectSeedView.SCAN_SEED,
        ),

        # Back to ScanView, this time feeding it a SeedQR.
        FlowStep(
            scan_views.ScanSeedQRView,
            before_run=load_seed_into_decoder,
        ),

        # Seed scanned, framework lands on SeedFinalizeView. Click
        # FINALIZE to commit the seed into storage.
        FlowStep(
            seed_views.SeedFinalizeView,
            button_data_selection=seed_views.SeedFinalizeView.FINALIZE,
        ),

        # SeedOptionsView is reached but redirects immediately because
        # the controller is in the middle of a PSBT flow.
        # is_redirect=True tells the framework not to expect a render.
        FlowStep(seed_views.SeedOptionsView, is_redirect=True),

        # Now we're walking through the PSBT review screens. No
        # button_data_selection means "default forward" (button index 0).
        FlowStep(psbt_views.PSBTOverviewView),
        FlowStep(psbt_views.PSBTMathView),

        # PSBTAddressDetailsView — pass button index 0 directly via
        # button_data_selection to click the only button on screen.
        FlowStep(psbt_views.PSBTAddressDetailsView, button_data_selection=0),

        # Three change outputs to walk through; each NEXT click stays
        # on PSBTChangeDetailsView with an incremented change_address_num.
        FlowStep(
            psbt_views.PSBTChangeDetailsView,
            button_data_selection=psbt_views.PSBTChangeDetailsView.NEXT,
        ),
        FlowStep(
            psbt_views.PSBTChangeDetailsView,
            button_data_selection=psbt_views.PSBTChangeDetailsView.NEXT,
        ),
        FlowStep(
            psbt_views.PSBTChangeDetailsView,
            button_data_selection=psbt_views.PSBTChangeDetailsView.NEXT,
        ),

        # On the finalize screen, click APPROVE_PSBT to sign.
        FlowStep(
            psbt_views.PSBTFinalizeView,
            button_data_selection=psbt_views.PSBTFinalizeView.APPROVE_PSBT,
        ),

        # Signed QR is shown. The last FlowStep with no fields just
        # asserts arrival on MainMenuView once the QR display loop ends.
        FlowStep(psbt_views.PSBTSignedQRDisplayView),
        FlowStep(MainMenuView),
    ])
```

### Quick rules

- The first `FlowStep` is always `MainMenuView` (or wherever the test
  starts). The framework boots the Controller there.
- The last `FlowStep` typically has no interaction fields — it's just an
  assertion that the flow ended on the expected View.
- Use `screen_return_value` instead of `button_data_selection` when the
  Screen returns something other than a button index (e.g. a dict from a
  passphrase keyboard, or a raw integer from a slider).
- Each consecutive pair of `expected_view` values represents one tested
  navigation **edge** in the View graph. That's what coverage tooling
  uses to compute which edges have tests.

### Where to read more

- [`base.py`](base.py) — full source of `FlowStep`, `FlowTest`, and
  `run_sequence()`.
- [`test_flows_seed.py`](test_flows_seed.py) — the largest existing
  flow-test file; good source of patterns for seed-related flows.
- [`test_flows_psbt.py`](test_flows_psbt.py) — PSBT-signing flow
  examples, including multisig and OP_RETURN paths.
