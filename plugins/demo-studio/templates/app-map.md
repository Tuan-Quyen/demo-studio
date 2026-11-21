# App map: <app>

- target: <URL or app path>
- Platform: <from demo.yaml>
- Data: seeded <how the demo account/data is created and reset> (real only if demo.yaml says so)

## Flows
| Flow | Start state | Steps (selector) | End state | Risks |
|---|---|---|---|---|
| <name> | <state> | <step: role/test-id/label> | <state> | <popups, slow loads> |

## Sensitive elements
(also listed in demo.yaml `privacy.mask` / `patterns`)
| Where | Selector | What it shows |
|---|---|---|
| <screen> | <css> | <email, token, name...> |
