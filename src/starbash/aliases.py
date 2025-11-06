import string

from starbash.exception import UserHandledError

_translator = str.maketrans("", "", string.punctuation + string.whitespace)


def normalize_target_name(name: str | None) -> str | None:
    """Converts a target name to an any filesystem-safe format by removing spaces"""
    if name is None:
        return None
    return name.replace(" ", "").lower()


def pre_normalize(name: str) -> str:
    """Pre-normalize a name by removing all whitespace and punctuation, and converting to lowercase.

    Args:
        name: The name to pre-normalize.

    Returns:
        Normalized string with only alphanumeric characters in lowercase.
    """
    # Create translation table that removes all punctuation and whitespace
    return name.lower().translate(_translator)


class UnrecognizedAliasError(UserHandledError):
    """Exception raised when an unrecognized alias is encountered during normalization."""

    pass


class Aliases:
    def __init__(self, alias_dict: dict[str, list[str]]):
        """Initialize the Aliases object with a dictionary mapping keys to their alias lists.

        The alias_dict structure follows the TOML format:
        - Keys are reference names used in code (e.g., "dark", "flat", "bias", "fits", "SiiOiii", "HaOiii")
        - Values are lists of aliases where the FIRST item is the canonical/preferred name
        - The dictionary key may or may not match the canonical name

        Example from TOML:
            [aliases]
            dark = ["dark", "darks"]           # key "dark" -> canonical "dark"
            flat = ["flat", "flats"]           # key "flat" -> canonical "flat"
            SiiOiii = ["SiiOiii", "SII-OIII", "S2-O3"]  # key "SiiOiii" -> canonical "SiiOiii"
        """
        self.alias_dict = alias_dict
        self.reverse_dict = {}

        # Build reverse lookup: any alias variant maps to canonical name
        for _key, aliases in alias_dict.items():
            if not aliases:
                continue
            # The first item in the list is ALWAYS the canonical/preferred form
            canonical = aliases[0]
            for alias in aliases:
                # Map each alias (case-insensitive) to the canonical form (first in list)
                # Also remove spaces, hypens and underscores when matching for normalization
                self.reverse_dict[pre_normalize(alias)] = canonical

    def get(self, name: str) -> list[str] | None:
        """Get the list of aliases for a given key name.

        Args:
            name: The key name to look up (as used in code/TOML)

        Returns:
            List of all aliases for this key, or None if not found.
            The first item in the returned list is the canonical form.
        """
        return self.alias_dict.get(name)

    def normalize(self, name: str) -> str:
        """Normalize a name to its canonical form using aliases.

        This performs case-insensitive matching to find the canonical form.
        The canonical form is the first item in the alias list from the TOML.

        Args:
            name: The name to normalize (e.g., "darks", "FLAT", "HA-OIII")

        Returns:
            The canonical/preferred form (e.g., "dark", "flat", "HaOiii"), or None if not found

        Examples:
            normalize("darks") -> "dark"
            normalize("FLAT") -> "flat"
            normalize("HA-OIII") -> "HaOiii"
        """
        result = self.reverse_dict.get(pre_normalize(name))
        if not result:
            raise UnrecognizedAliasError(f"'{name}' not found in aliases.")
        return result

    def equals(self, name1: str, name2: str) -> bool:
        """Check if two names are equivalent based on aliases."""
        norm1 = self.normalize(name1.strip())
        norm2 = self.normalize(name2.strip())
        return norm1 == norm2
