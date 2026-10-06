"""Serialized, journaled lifecycle; all test seams are Python objects, not CLI flags."""
import uuid
from . import ownership as rb
from .policy import SSID, ADDRESS, STA
from .state import owner_for
from .uplink import Uplink, LOCAL
from .wifi import Plan, from_dict


class Controller:
    def __init__(self, backend, store):
        self.b, self.s = backend, store

    def owner(self, data):
        return owner_for(data, self.s.boot_id)

    def status(self, data=None, error=None):
        value = {'schema': 1, 'mode': 'off', 'phase': 'off', 'ssid': SSID, 'ipv4': None,
                 'interface': None, 'profile_uuid': None, 'clients': 0, 'uplink': None,
                 'client_count': 0, 'client_details': [], 'client_data_status': 'OFF',
                 'configured': self.s.configured(), 'physical_client_validation': 'NOT_TESTED',
                 'wifi_uplink': 'UNVALIDATED_DISABLED', 'health': 'OK', 'error': error}
        import time
        value['updated_monotonic'] = time.monotonic()
        value['boot_id'] = self.s.boot_id
        if data:
            owner = self.owner(data)
            value.update(mode=data['mode'], phase=data['phase'], interface=owner.vif,
                         profile_uuid=owner.profile_uuid, ipv4=ADDRESS)
            value.update(clients=None, client_count=None, client_data_status='UNAVAILABLE')
            if data['phase'] == 'active': value.update(self.b.client_snapshot(owner))
        if data and data['mode']=='local': value.update(LOCAL.status())
        else:
            selected=Uplink(**data['uplink_snapshot']) if data and data.get('uplink_snapshot') else self.b.detect_uplink()
            value.update(selected.status())
        if error: value['health'] = 'ERROR'
        return value

    def new_state(self, mode):
        links = self.b.links()
        raw = {'schema': 1, 'test_id': str(uuid.uuid4()), 'boot_id': self.s.boot_id,
               'baseline': {'profile_uuids': sorted(self.b.profiles()),
                            'interface_names': sorted(x['ifname'] for x in links),
                            'interface_macs': sorted(set(x['address'].lower() for x in links if x.get('address'))),
                            'wifi_radio': self.b.radio(), 'sta_autoconnect': self.b.autoconnect()},
               'resources': {'profile_uuid': str(uuid.uuid4()), 'vif_ifindex': None, 'nft_handle': None},
               'changes': {'wifi_radio_enabled': False, 'sta_autoconnect_disabled': False}}
        data = {'schema': 1, 'ownership': raw, 'phase': 'starting', 'mode': mode,
                'radio_touched': False, 'auto_touched': False, 'guard_digest': None,
                'uplink_snapshot':None, 'radio_plan':Plan().public()}
        self.owner(data)
        return data

    def start(self, mode):
        if mode not in ('local', 'internet'): raise rb.SafetyError('Unsupported mode')
        data = self.s.load()
        if data:
            if data['phase'] != 'active':
                raise rb.OperationError('An incomplete session requires off before retrying')
            return self.switch(data, mode)
        password = self.s.password()  # Refuse before changing anything if not configured.
        uplink,plan=self.b.preflight(mode)
        data = self.new_state(mode)
        data['uplink_snapshot']=uplink.public() if uplink else None
        data['radio_plan']=plan.public()
        self.b.planned_absent(self.owner(data))
        self.s.save(data)
        owner = self.owner(data)
        try:
            self.s.publish(self.status(data))
            self.b.arm_watch()  # Must succeed before first radio/network change.
            handle, digest = self.b.guard(owner, 'blocked', create=True)
            data['ownership']['resources']['nft_handle'] = handle
            data['guard_digest'] = digest
            self.s.save(data)
            owner = self.owner(data)
            # Idle path retains the validated anti-autoconnect sequence. STA+AP
            # never toggles the radio or upstream device/autoconnect setting.
            if not plan.sta_interface:
                if self.b.autoconnect():
                    data['auto_touched'] = True
                    self.s.save(data)
                    self.b.run(['/usr/bin/nmcli', 'device', 'set', STA, 'autoconnect', 'no'])
                if not self.b.wifi_idle(): raise rb.OperationError('Wi-Fi became active before creation')
                data['radio_touched'] = True
                self.s.save(data)
                if self.b.radio() == 'enabled': self.b.run(['/usr/bin/nmcli', 'radio', 'wifi', 'off'])
            else:self.b.verify_plan(plan)
            data['ownership']['resources']['vif_ifindex'] = self.b.create_interface(owner)
            self.s.save(data)
            owner = self.owner(data)
            self.b.add_profile(owner, password, plan)
            password = None
            rb.Rollback(owner, self.b, emit=lambda _: None).inspect()
            if mode == 'internet': self.b.require_uplink(uplink)
            if not plan.sta_interface:self.b.run(['/usr/bin/nmcli', 'radio', 'wifi', 'on'])
            self.b.wait_device_ready(owner)
            # The wait creates a window for external changes: revalidate ownership
            # and selected routing before the single activation request.
            rb.Rollback(owner, self.b, emit=lambda _: None).inspect()
            if mode == 'internet': self.b.require_uplink(uplink)
            self.b.verify_plan(plan)
            self.b.activate(owner)
            _, data['guard_digest'] = self.b.guard(owner, mode, uplink=uplink.interface if uplink else None)
            self.b.healthy(owner, mode, data['guard_digest'], uplink, plan)
            data['phase'] = 'active'
            self.s.save(data)
            value = self.status(data)
            self.s.publish(value)
            return value
        except BaseException:
            try: self.stop()
            except Exception:
                self.s.publish(self.status(self.s.load(), 'RECOVERY_REQUIRED'))
            raise

    def switch(self, data, mode):
        owner = self.owner(data)
        # Local downgrade never inspects or requires an Internet route.
        rb.Rollback(owner, self.b, emit=lambda _: None).inspect()
        uplink=self.b.require_uplink() if mode=='internet' else None
        plan=from_dict(data['radio_plan'])
        if uplink and uplink.type=='WIFI' and not plan.sta_interface:
            raise rb.OperationError('WIFI_STA_AP_RESTART_REQUIRED')
        data['phase'] = 'switching'
        self.s.save(data)
        try:
            self.s.publish(self.status(data))
            _, data['guard_digest'] = self.b.guard(owner, mode, uplink=uplink.interface if uplink else None)
            data['mode'] = mode
            data['uplink_snapshot']=uplink.public() if uplink else None
            self.b.healthy(owner, mode, data['guard_digest'], uplink, plan)
            data['phase'] = 'active'
            self.s.save(data)
            value = self.status(data)
            self.s.publish(value)
            return value
        except BaseException:
            try: self.stop()
            except Exception: self.s.publish(self.status(self.s.load(), 'RECOVERY_REQUIRED'))
            raise

    def stop(self):
        # Internal cleanup API: caller already holds Store.locked(). start(),
        # switch() and tick() call this directly, never the public helper/off.
        data = self.s.load()
        if not data:
            value = self.status()
            self.s.publish(value)
            return value
        owner = self.owner(data)
        rb.Rollback(owner, self.b, emit=lambda _: None).inspect()
        data['phase'] = 'stopping'
        self.s.save(data)
        self.s.publish(self.status(data))
        if self.b.table(owner) is not None:
            # If construction failed before writing the table handle, record the
            # marker-proven receipt first; never adopt an unrelated table.
            if owner.table_handle is None:
                data['ownership']['resources']['nft_handle'] = self.b.table(owner)['handle']
                self.s.save(data)
                owner = self.owner(data)
            self.b.guard(owner, 'blocked')
        rb.Rollback(owner, self.b, emit=lambda _: None).execute(apply=True)
        self.b.remove_lease(owner)
        base = data['ownership']['baseline']
        if data['radio_touched'] and self.b.radio() != base['wifi_radio']:
            if base['wifi_radio'] == 'disabled' and not self.b.wifi_idle():
                raise rb.OperationError('New Wi-Fi link preserved; radio restoration deferred')
            self.b.run(['/usr/bin/nmcli', 'radio', 'wifi', 'on' if base['wifi_radio'] == 'enabled' else 'off'])
            if self.b.radio() != base['wifi_radio']: raise rb.OperationError('Radio restoration failed')
        if data['auto_touched'] and self.b.autoconnect() != base['sta_autoconnect']:
            self.b.run(['/usr/bin/nmcli', 'device', 'set', STA, 'autoconnect', 'yes'])
            if not self.b.autoconnect(): raise rb.OperationError('Autoconnect restoration failed')
        self.s.clear()
        value = self.status()
        self.s.publish(value)
        return value

    def tick(self):
        data = self.s.load()
        if not data: return False
        if data['phase'] != 'active':
            self.stop()
            return False
        try:
            self.b.healthy(self.owner(data), data['mode'], data['guard_digest'],
                           Uplink(**data['uplink_snapshot']) if data['uplink_snapshot'] else None, from_dict(data['radio_plan']))
            self.s.publish(self.status(data))
        except Exception:
            self.stop()
            self.s.publish(self.status(error='SESSION_STOPPED_AFTER_HEALTH_FAILURE'))
            return False
        return True
