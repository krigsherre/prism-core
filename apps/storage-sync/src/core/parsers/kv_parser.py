from typing import Dict


class KeyValueParser:
    """
    Domain service for parsing key-value text pairs and form fields.
    """

    @classmethod
    def parse(cls, content: str) -> Dict[str, str]:
        """Parse key-value pair lines separated by colon or equals sign."""
        if not content:
            return {}
        from core.parsers.table_parser import TableParser
        if TableParser.is_otsl(content):
            return {}

        result: Dict[str, str] = {}
        lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
        for line in lines:
            if ": " in line or (":" in line and "=" not in line.split(":", 1)[0]):
                k, v = line.split(":", 1)
                result[k.strip()] = v.strip()
            elif line.count("=") == 1 and len(line) < 200:
                k, v = line.split("=", 1)
                if k.strip() and not any(ch.isdigit() for ch in k.strip()[:3]):
                    result[k.strip()] = v.strip()
        return result
