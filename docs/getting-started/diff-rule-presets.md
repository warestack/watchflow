# Diff rule presets (threading guardrails)

These presets use the diff-aware validators already supported by Watchflow. Paste them directly into `.watchflow/rules.yaml` or upload to watchflow.dev as a YAML file. They avoid any unsupported sections (no `actions`, only `description`, `enabled`, `severity`, `event_types`, and `parameters` with `file_patterns`, `require_patterns`, `forbidden_patterns`).

## Preset file

The file `docs/assets/threading-guardrails.yaml` contains ready-to-use rules:

```yaml
rules:
  - description: "Prefer ThreadPoolExecutor over raw threading.Thread"
    enabled: true
    severity: "medium"
    event_types: ["pull_request"]
    parameters:
      file_patterns: ["**/*.py"]
      forbidden_patterns:
        - "threading\\.Thread"
      require_patterns:
        - "concurrent\\.futures\\.ThreadPoolExecutor"

  - description: "Require locks when using threading for shared data"
    enabled: true
    severity: "high"
    event_types: ["pull_request"]
    parameters:
      file_patterns: ["**/*.py"]
      require_patterns:
        - "threading\\.Lock"

  - description: "Use queue.Queue for thread communication (avoid shared lists/dicts)"
    enabled: true
    severity: "medium"
    event_types: ["pull_request"]
    parameters:
      file_patterns: ["**/*.py"]
      require_patterns:
        - "queue\\.Queue"

  - description: "Limit ThreadPoolExecutor max_workers to 10"
    enabled: true
    severity: "medium"
    event_types: ["pull_request"]
    parameters:
      file_patterns: ["**/*.py"]
      forbidden_patterns:
        - "ThreadPoolExecutor\\(max_workers\\s*=\\s*(1[1-9]|[2-9][0-9])"
```

## How to use on watchflow.dev

1) Click “Upload config” (or paste the YAML directly if enabled).  
2) Ensure event type is `pull_request`.  
3) Adjust file globs or regexes as needed for your repo.  

If the form still shows “Rule not supported,” it means the UI is filtering diff-pattern rules. In that case, use the YAML upload path or apply the config directly in your repo. A follow-up change to the site can whitelist these presets so they appear without warnings.

