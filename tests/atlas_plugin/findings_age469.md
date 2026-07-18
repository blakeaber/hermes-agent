# AGE-469 Atlas Plugin – Findings & Root Cause Analysis

## Summary

Investigation into the AGE-469 failure surface for the Atlas plugin revealed
that the plugin was not producing findings during scheduled scans. The root
cause is a combination of missing runtime configuration and network isolation
that prevents the plugin from reaching the Atlas API endpoint.

---

## Root Cause

### 1. Missing plugin configuration (`atlas_plugin` section absent)

The Atlas plugin requires an `[atlas_plugin]` section (or equivalent
environment variables) to be present in the service configuration at startup.
When this section is absent the plugin initialises in a **no-op / disabled
state** and silently skips all scan cycles without emitting an error.

Affected config keys:
| Key | Purpose | Default |
|-----|---------|---------|
| `ATLAS_API_URL` | Base URL of the Atlas REST API | *(none – required)* |
| `ATLAS_API_KEY` | Authentication token | *(none – required)* |
| `ATLAS_PLUGIN_ENABLED` | Feature flag to activate the plugin | `false` |

In the affected environment **all three values were unset**, causing the plugin
to remain disabled.

### 2. Network isolation (egress blocked)

Even when the configuration is supplied, the deployment environment enforces
an egress deny-all policy by default. The Atlas API hostname was not added to
the egress allow-list, so any attempt by the plugin to reach the API results
in a connection timeout rather than a meaningful error response.

### 3. Plugin disabled via feature flag

`ATLAS_PLUGIN_ENABLED` defaults to `false` as a safety measure. The flag must
be explicitly set to `true` in the environment or secrets store; it is not
sufficient to supply the URL and key alone.

---

## Evidence

- Log lines showing `atlas_plugin: disabled, skipping scan` at every scheduled
  interval confirm the no-op initialisation path.
- Network probe from within the pod: `curl -v $ATLAS_API_URL` times out after
  30 s, confirming the egress block.
- Config diff between staging (working) and production (broken) shows the
  three keys listed above are absent from the production secret.

---

## Recommended Fix Path

1. **Add the missing secret values** to the production secrets store (Vault /
   Kubernetes Secret) for the three keys above.

2. **Enable the plugin** by setting `ATLAS_PLUGIN_ENABLED=true` in the same
   secret or config map.

3. **Update the egress policy** to allow outbound HTTPS (port 443) to the
   Atlas API hostname. Example (Kubernetes NetworkPolicy):

   ```yaml
   egress:
     - to:
         - ipBlock:
             cidr: <atlas-api-cidr>/32
       ports:
         - protocol: TCP
           port: 443
   ```

4. **Redeploy** the affected service and confirm findings appear in the next
   scheduled scan cycle (typically within 5 minutes).

5. **Add a startup health-check** that fails fast when `ATLAS_PLUGIN_ENABLED`
   is `true` but the required keys are missing, to prevent silent no-op
   behaviour in future deployments.

---

## Status

- [ ] Secret values added to production
- [ ] Egress policy updated
- [ ] Service redeployed and findings confirmed
- [ ] Startup health-check implemented (tracked in follow-up ticket)
