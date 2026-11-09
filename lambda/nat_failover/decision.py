"""NAT path state machine. No AWS calls; apply the same policy to either AZ.

Adapted from the separately exercised 2026-11-03 controller. A primary health
probe NEVER follows the app's bypass route. Unknown control results fail closed.
"""
import ipaddress


def valid_sample(sample):
    if sample.get('valid') is not True or type(sample.get('ok')) is not bool:
        return False
    if not sample['ok']:
        return sample.get('ip') is None
    try:
        return ipaddress.ip_address(sample['ip']).version == 4
    except (ValueError, KeyError, TypeError):
        return False


def decide(state, samples, current_nat, cfg, now):
    s = dict(state)
    for key in ('failures', 'recoveries', 'last_switch'):
        s[key] = int(s.get(key, 0))
    app, primary, alternate = (samples.get(k, {}) for k in ('app', 'primary', 'alternate'))
    if not all(valid_sample(v) for v in (app, primary, alternate)):
        s.update(failures=0, recoveries=0)
        return s, None, 'CONTROL_UNKNOWN'
    if current_nat not in (cfg['primary']['id'], cfg['alternate']['id']):
        s.update(failures=0, recoveries=0)
        return s, None, 'UNEXPECTED_ROUTE'
    # A successful native-path probe with the wrong IP indicates drift, not a
    # failed NAT. Never turn an unrecognised egress path into permission to write.
    if any(p['ok'] and p['ip'] != cfg[k]['ip'] for k, p in [('primary', primary), ('alternate', alternate)]):
        s.update(failures=0, recoveries=0)
        return s, None, 'PROBE_PATH_MISMATCH'
    expected_ip = cfg['primary']['ip'] if current_nat == cfg['primary']['id'] else cfg['alternate']['ip']
    if app['ok'] and app['ip'] != expected_ip:
        s.update(failures=0, recoveries=0)
        return s, None, 'APP_PATH_MISMATCH'
    if current_nat == cfg['primary']['id']:
        s['recoveries'] = 0
        bad = not app['ok'] and not primary['ok'] and alternate['ok']
        s['failures'] = min(s['failures'] + 1, cfg['failure_threshold']) if bad else 0
        if s['failures'] >= cfg['failure_threshold']:
            return s, cfg['alternate']['id'], 'FAILOVER'
        if bad:
            return s, None, 'FAILURE_PENDING'
        reason = ('NORMAL' if app['ok'] and primary['ok'] else
                  'NO_HEALTHY_ALTERNATE' if not primary['ok'] and not alternate['ok'] else
                  'APP_FAILURE_NATIVE_HEALTHY' if primary['ok'] else 'PATH_DISAGREEMENT')
        return s, None, reason
    s['failures'] = 0
    # Native-path success is the evidence of recovery. App success on the bypass
    # alone never proves the original NAT recovered. If the alternate fails too,
    # three independently successful native checks can still recover the app.
    s['recoveries'] = min(s['recoveries'] + 1, cfg['recovery_threshold']) if primary['ok'] else 0
    held = now - s['last_switch'] >= cfg['minimum_bypass_seconds']
    if s['recoveries'] >= cfg['recovery_threshold'] and held:
        return s, cfg['primary']['id'], 'FAILBACK'
    return s, None, 'RECOVERY_PENDING' if primary['ok'] else ('BYPASS_CONFIRMED' if app['ok'] else 'BYPASS_NOT_CONFIRMED')
