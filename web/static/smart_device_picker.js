(() => {
    const pickers = [...document.querySelectorAll('[data-smart-device-picker]')];
    if (!pickers.length) return;

    const field = (picker, name) =>
        picker.closest('form')?.querySelector(`[name="${name}"]`) || null;

    function setManual(picker, enabled) {
        const select = picker.querySelector('[data-smart-device-select]');
        const manual = picker.querySelector('[data-smart-device-manual]');
        const hidden = picker.querySelector('[data-smart-device-value]');
        const toggle = picker.querySelector('[data-smart-device-manual-toggle]');

        picker.dataset.manual = enabled ? '1' : '0';
        select.hidden = enabled;
        manual.hidden = !enabled;
        toggle.textContent = enabled ? 'Aus Liste wählen' : 'Manuell eingeben';

        if (enabled) {
            manual.value = hidden.value || manual.value || '';
        }
    }

    async function loadDisks(picker, forceRefresh = false) {
        const select = picker.querySelector('[data-smart-device-select]');
        const manual = picker.querySelector('[data-smart-device-manual]');
        const hidden = picker.querySelector('[data-smart-device-value]');
        const status = picker.querySelector('[data-smart-device-status]');
        const miniguard = field(picker, 'miniguard_id');
        const source = field(picker, 'execution_source');

        if (source && source.value !== 'miniguard') {
            setManual(picker, true);
            status.textContent = 'Lokale Prüfung: direkten Gerätepfad unter /dev eingeben.';
            return;
        }

        const agentId = miniguard?.value?.trim() || '';
        if (!agentId) {
            select.innerHTML = '<option value="">Zuerst MiniGuard auswählen ...</option>';
            setManual(picker, false);
            status.textContent = 'Wähle zuerst den MiniGuard aus, auf dem sich der Datenträger befindet.';
            return;
        }

        select.disabled = true;
        status.textContent = 'Lade Datenträger aus dem MiniGuard-Inventar ...';

        try {
            const refreshSuffix = forceRefresh ? '?refresh=1' : '';
            const response = await fetch(
                `/api/miniguards/${encodeURIComponent(agentId)}/disks${refreshSuffix}`,
                {
                    credentials: 'same-origin',
                    headers: { 'Accept': 'application/json' }
                }
            );
            const data = await response.json();

            if (!response.ok || !data.ok) {
                throw new Error(data.error || `HTTP ${response.status}`);
            }

            const current = hidden.value || picker.dataset.currentDevice || '';
            select.innerHTML = '<option value="">Datenträger auswählen ...</option>';

            for (const disk of data.disks || []) {
                const option = document.createElement('option');
                option.value = disk.path;

                const label = [];
                if (disk.model) label.push(disk.model);
                if (disk.size_human) label.push(disk.size_human);
                if (disk.serial) label.push(`SN ${disk.serial}`);
                label.push(disk.path);

                option.textContent = label.join(' · ');
                if (disk.path === current) {
                    option.selected = true;
                }
                select.appendChild(option);
            }

            if (!(data.disks || []).length) {
                setManual(picker, true);
                status.textContent =
                    'Im gespeicherten Inventar wurden keine Datenträger gefunden. Manuelle Eingabe ist möglich.';
                return;
            }

            setManual(picker, false);
            status.textContent =
                `${data.disks.length} Datenträger gefunden` +
                (data.source === 'live' ? ' · live abgefragt' : ' · aus Inventar') +
                (data.inventory_updated_at
                    ? ` · ${data.inventory_updated_at.replace('T', ' ')}`
                    : '') +
                '.';

            if (
                current &&
                ![...select.options].some(option => option.value === current)
            ) {
                setManual(picker, true);
                manual.value = current;
                status.textContent +=
                    ' Der bisherige Gerätepfad ist nicht mehr im Inventar enthalten.';
            }
        } catch (error) {
            setManual(picker, true);
            status.textContent =
                `Datenträger konnten nicht geladen werden: ${error.message}. Manuelle Eingabe bleibt möglich.`;
        } finally {
            select.disabled = false;
        }
    }

    for (const picker of pickers) {
        const select = picker.querySelector('[data-smart-device-select]');
        const manual = picker.querySelector('[data-smart-device-manual]');
        const hidden = picker.querySelector('[data-smart-device-value]');
        const refresh = picker.querySelector('[data-smart-device-refresh]');
        const toggle = picker.querySelector('[data-smart-device-manual-toggle]');
        const miniguard = field(picker, 'miniguard_id');
        const source = field(picker, 'execution_source');

        select.addEventListener('change', () => {
            hidden.value = select.value;
            picker.dataset.currentDevice = select.value;
        });

        manual.addEventListener('input', () => {
            hidden.value = manual.value.trim();
            picker.dataset.currentDevice = hidden.value;
        });

        refresh.addEventListener('click', () => loadDisks(picker, true));

        toggle.addEventListener('click', () => {
            const wasManual = picker.dataset.manual === '1';
            setManual(picker, !wasManual);
            if (wasManual) {
                loadDisks(picker);
            }
        });

        miniguard?.addEventListener('change', () => {
            hidden.value = '';
            picker.dataset.currentDevice = '';
            loadDisks(picker);
        });

        source?.addEventListener('change', () => loadDisks(picker));

        loadDisks(picker);
    }
})();
