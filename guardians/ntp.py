import socket
import struct
import time

from guardians.base import BaseGuardian

NTP_DELTA = 2208988800

class Guardian(BaseGuardian):
    GUARDIAN = {"id":"ntp","name":"NTP Guardian","version":"1.0.0","description":"Prüft NTP-Server, Zeitabweichung, Roundtrip und Stratum","icon":"clock","category":"Netzwerk","service_family":"ntp"}
    CONFIG_SCHEMA = {
        "name":{"type":"text","label":"Name","required":True},"id":{"type":"slug","label":"Guardian-ID"},"device_id":{"type":"hidden","label":"Geräte-ID"},
        "interval":{"type":"number","label":"Intervall (Sekunden)","default":300,"min":30},"timeout":{"type":"number","label":"Timeout (Sekunden)","default":5,"min":1},"retries":{"type":"number","label":"Fehlversuche bis Critical","default":3,"min":1},
        "server":{"type":"text","label":"NTP-Server","required":True,"default":"pool.ntp.org"},
        "warning_offset_ms":{"type":"number","label":"Warning ab Zeitabweichung (ms)","default":500,"min":0},
        "critical_offset_ms":{"type":"number","label":"Critical ab Zeitabweichung (ms)","default":2000,"min":0},
        "warning_roundtrip_ms":{"type":"number","label":"Warning ab Roundtrip (ms)","default":500,"min":0},
        "critical_roundtrip_ms":{"type":"number","label":"Critical ab Roundtrip (ms)","default":2000,"min":0},
    }
    REQUIRED=("server",)
    def run(self):
        server=str(self.check['server']).strip(); details={"guardian":self.GUARDIAN,"server":server}; started=time.monotonic()
        packet=bytearray(48); packet[0]=0x1b
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); sock.settimeout(self.timeout)
        t1=time.time()
        try:
            sock.sendto(packet,(server,123)); data,_=sock.recvfrom(512); t4=time.time()
        except (OSError,socket.timeout) as error:
            details['error']=str(error); return self.critical(f"{self.name}: NTP-Abfrage fehlgeschlagen: {error}",details=details)
        finally: sock.close()
        if len(data)<48: return self.critical(f"{self.name}: Ungültige NTP-Antwort",details=details)
        unpacked=struct.unpack('!12I',data[:48]); stratum=data[1]
        t2=unpacked[8]-NTP_DELTA + unpacked[9]/2**32; t3=unpacked[10]-NTP_DELTA + unpacked[11]/2**32
        offset=((t2-t1)+(t3-t4))/2; delay=(t4-t1)-(t3-t2)
        offset_ms=abs(offset*1000); roundtrip_ms=max(0,delay*1000); ms=int((time.monotonic()-started)*1000)
        details.update(stratum=stratum,offset_ms=round(offset*1000,2),roundtrip_ms=round(roundtrip_ms,2))
        if stratum==0 or stratum>15: return self.critical(f"{self.name}: Ungültiges NTP-Stratum {stratum}",ms,details)
        c_off=float(self.check.get('critical_offset_ms',2000) or 0); w_off=float(self.check.get('warning_offset_ms',500) or 0)
        c_rt=float(self.check.get('critical_roundtrip_ms',2000) or 0); w_rt=float(self.check.get('warning_roundtrip_ms',500) or 0)
        if (c_off and offset_ms>=c_off) or (c_rt and roundtrip_ms>=c_rt): return self.critical(f"{self.name}: Abweichung {offset_ms:.1f} ms, Roundtrip {roundtrip_ms:.1f} ms",ms,details)
        if (w_off and offset_ms>=w_off) or (w_rt and roundtrip_ms>=w_rt): return self.warning(f"{self.name}: Abweichung {offset_ms:.1f} ms, Roundtrip {roundtrip_ms:.1f} ms",ms,details)
        return self.ok(f"{self.name}: Abweichung {offset_ms:.1f} ms, Stratum {stratum}",ms,details)
