# Data repair dispatcher wrapper

Added a state-agnostic `data_repair` dispatcher at `agent/scripts/data_repair.py` that routes a dataframe to the correct jurisdiction-specific repair script by filename convention.

## API

```python
def data_repair(df: pd.DataFrame, jurisdiction: str, state: str) -> pd.DataFrame
```

The wrapper does not filter `df`; the caller should pass the jurisdiction slice. It resolves the script path, imports the module via `importlib`, and returns that module's `data_repair(df)`.

## Path convention

```text
agent/scripts/{state_lower}/data_repair_{state_lower}_{slug}.py
```

Slug: NFKD-normalize the jurisdiction name, strip combining marks, lowercase, replace non-alphanumeric runs with `_`. No override map; missing scripts raise `FileNotFoundError` with the expected path.

## Artifacts

- `agent/scripts/data_repair.py`

## Checks

Resolved and imported modules for Anaheim/CA, La Cañada Flintridge/CA, Sacramento County/CA, Houston/TX, and Chicago/IL; end-to-end empty-frame dispatch succeeded for Houston and Anaheim.
