from plugin_packages import package_metadata_for_storage


TYPE_LABELS = {
    "guardian": "Guardian",
    "beacon": "Beacon",
    "portal": "Portal",
}


def module_key(module_type, module_name):
    return f"{module_type}:{module_name}"


def aggregate_modules(
    guardians,
    beacons,
    portals,
    config,
    guardian_path,
    beacon_path,
    portal_path,
):
    collections = {
        "guardian": guardians,
        "beacon": beacons,
        "portal": portals,
    }
    result = []

    for module_type, items in collections.items():
        for raw in items:
            item = dict(raw)
            module_name = str(item.get("module", ""))
            source = item.get("source")
            if not source:
                source = (
                    "custom"
                    if module_name.startswith("custom:")
                    else "builtin"
                )
            file_module = str(
                item.get("file_module")
                or module_name.removeprefix("custom:")
            )
            manifest = {}
            readme = ""
            if source == "custom":
                path_factory = {
                    "guardian": guardian_path,
                    "beacon": beacon_path,
                    "portal": portal_path,
                }[module_type]
                plugin_file = path_factory(file_module)
                if plugin_file.exists():
                    manifest, _, readme = package_metadata_for_storage(
                        plugin_file
                    )

            instance_count = count_instances(
                module_type,
                module_name,
                config,
            )
            item.update({
                "key": module_key(module_type, module_name),
                "type": module_type,
                "type_label": TYPE_LABELS[module_type],
                "source": source,
                "file_module": file_module,
                "manifest": manifest,
                "readme": readme,
                "instance_count": instance_count,
                "version": (
                    manifest.get("version")
                    or item.get("version")
                    or "—"
                ),
                "author": (
                    manifest.get("author")
                    or item.get("author")
                    or "LANaxy"
                ),
                "minimum_lanaxy_version": manifest.get(
                    "minimum_lanaxy_version",
                    "",
                ),
                "status": item.get("status", "loaded"),
            })
            result.append(item)

    return sorted(
        result,
        key=lambda item: (
            item["type"],
            str(item.get("name", item["module"])).lower(),
        ),
    )


def count_instances(module_type, module_name, config):
    if module_type == "guardian":
        return sum(
            1
            for item in config.get("checks", [])
            if item.get("guardian") == module_name
        )
    if module_type == "beacon":
        return sum(
            1
            for item in config.get(
                "notifications",
                {},
            ).get("channels", [])
            if item.get("type") == module_name
        )
    return sum(
        1
        for item in config.get("control", {}).get("portals", [])
        if item.get("type") == module_name
    )


def find_module(modules, module_type, module_name):
    return next(
        (
            item
            for item in modules
            if item["type"] == module_type
            and item["module"] == module_name
        ),
        None,
    )


def module_in_use(module_type, module_name, config):
    return count_instances(module_type, module_name, config) > 0


def version_tuple(value):
    parts = []
    for part in str(value or "0").split("."):
        digits = "".join(character for character in part if character.isdigit())
        parts.append(int(digits or 0))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def require_compatible_version(current_version, minimum_version):
    if not minimum_version:
        return
    if version_tuple(current_version) < version_tuple(minimum_version):
        raise ValueError(
            f"Dieses Modul benötigt LANaxy {minimum_version} oder neuer. "
            f"Installiert ist {current_version}."
        )
