import pytest

from starbash.aliases import Aliases, UnrecognizedAliasError


@pytest.fixture
def sample_aliases():
    """Sample alias dictionary matching the TOML structure."""
    return {
        "dark": ["dark", "darks"],
        "flat": ["flat", "flats"],
        "bias": ["bias", "biases"],
        "fits": ["fits", "fit"],
        "SiiOiii": ["SiiOiii", "SII-OIII", "S2-O3"],
        "HaOiii": ["HaOiii", "HA-OIII", "Halpha-O3"],
    }


@pytest.fixture
def aliases(sample_aliases):
    """Create an Aliases instance with sample data."""
    return Aliases(sample_aliases)


class TestAliasesInit:
    def test_init_creates_alias_dict(self, aliases, sample_aliases):
        """Test that __init__ stores the alias dictionary."""
        assert aliases.alias_dict == sample_aliases

    def test_init_creates_reverse_dict(self, aliases):
        """Test that __init__ creates a reverse lookup dictionary."""
        assert aliases.reverse_dict is not None
        assert len(aliases.reverse_dict) > 0

    def test_init_with_empty_dict(self):
        """Test initialization with an empty dictionary."""
        aliases = Aliases({})
        assert aliases.alias_dict == {}
        assert aliases.reverse_dict == {}

    def test_init_with_empty_list(self):
        """Test initialization with a key that has an empty list."""
        aliases = Aliases({"empty": []})
        assert "empty" in aliases.alias_dict
        # Empty list should not add entries to reverse_dict
        assert len(aliases.reverse_dict) == 0


class TestAliasesGet:
    def test_get_returns_alias_list(self, aliases):
        """Test that get() returns the list of aliases for a key."""
        result = aliases.get("dark")
        assert result == ["dark", "darks"]

    def test_get_returns_filter_aliases(self, aliases):
        """Test getting aliases for filter names."""
        result = aliases.get("SiiOiii")
        assert result == ["SiiOiii", "SII-OIII", "S2-O3"]

    def test_get_nonexistent_key(self, aliases):
        """Test that get() returns None for non-existent keys."""
        result = aliases.get("nonexistent")
        assert result is None

    def test_get_first_item_is_canonical(self, aliases):
        """Test that the first item in the returned list is the canonical form."""
        result = aliases.get("HaOiii")
        assert result[0] == "HaOiii"

    def test_get_case_sensitive_key(self, aliases):
        """Test that get() is case-sensitive for keys."""
        result = aliases.get("DARK")
        assert (
            result is None
        )  # Key lookup is case-sensitive (but normalize is case-insensitive)


class TestAliasesNormalize:
    def test_normalize_exact_match(self, aliases):
        """Test normalizing with exact canonical name."""
        assert aliases.normalize("dark") == "dark"
        assert aliases.normalize("flat") == "flat"

    def test_normalize_variant(self, aliases):
        """Test normalizing a variant to canonical form."""
        assert aliases.normalize("darks") == "dark"
        assert aliases.normalize("flats") == "flat"
        assert aliases.normalize("biases") == "bias"

    def test_normalize_case_insensitive(self, aliases):
        """Test that normalize() is case-insensitive."""
        assert aliases.normalize("DARK") == "dark"
        assert aliases.normalize("Dark") == "dark"
        assert aliases.normalize("DARKS") == "dark"
        assert aliases.normalize("Flats") == "flat"

    def test_normalize_filter_variants(self, aliases):
        """Test normalizing filter name variants."""
        assert aliases.normalize("SII-OIII") == "SiiOiii"
        assert aliases.normalize("S2-O3") == "SiiOiii"
        assert aliases.normalize("sii-oiii") == "SiiOiii"

    def test_normalize_ha_variants(self, aliases):
        """Test normalizing Ha filter variants."""
        assert aliases.normalize("HA-OIII") == "HaOiii"
        assert aliases.normalize("Halpha-O3") == "HaOiii"
        assert aliases.normalize("ha-oiii") == "HaOiii"

    def test_normalize_file_suffix(self, aliases):
        """Test normalizing file suffixes."""
        assert aliases.normalize("fits") == "fits"
        assert aliases.normalize("fit") == "fits"
        assert aliases.normalize("FIT") == "fits"
        assert aliases.normalize("FITS") == "fits"

    def test_normalize_nonexistent(self, aliases):
        """Test normalizing a non-existent alias raises UnrecognizedAliasError."""
        with pytest.raises(
            UnrecognizedAliasError, match="'nonexistent' not found in aliases"
        ):
            aliases.normalize("nonexistent")
        with pytest.raises(
            UnrecognizedAliasError, match="'unknown' not found in aliases"
        ):
            aliases.normalize("unknown")

    def test_normalize_returns_canonical(self, aliases):
        """Test that normalize always returns the first item (canonical form)."""
        # All variants should normalize to the first item in the list
        assert aliases.normalize("dark") == "dark"
        assert aliases.normalize("darks") == "dark"

        assert aliases.normalize("SiiOiii") == "SiiOiii"
        assert aliases.normalize("SII-OIII") == "SiiOiii"
        assert aliases.normalize("S2-O3") == "SiiOiii"


class TestAliasesEdgeCases:
    def test_single_item_list(self):
        """Test with a list containing only one item."""
        aliases = Aliases({"single": ["canonical"]})
        assert aliases.normalize("canonical") == "canonical"
        assert aliases.normalize("CANONICAL") == "canonical"

    def test_multiple_keys_same_canonical(self):
        """Test multiple keys that might have overlapping aliases."""
        aliases = Aliases(
            {
                "type1": ["canonical1", "alias1", "alias2"],
                "type2": ["canonical2", "alias3", "alias4"],
            }
        )
        assert aliases.normalize("alias1") == "canonical1"
        assert aliases.normalize("alias3") == "canonical2"
        assert aliases.normalize("ALIAS1") == "canonical1"

    def test_special_characters_in_names(self):
        """Test aliases with special characters."""
        aliases = Aliases(
            {
                "ha_filter": ["Ha-OIII", "HA-OIII", "Halpha/O3"],
            }
        )
        assert aliases.normalize("Ha-OIII") == "Ha-OIII"
        assert aliases.normalize("ha-oiii") == "Ha-OIII"
        assert aliases.normalize("Halpha/O3") == "Ha-OIII"

    def test_whitespace_handling(self):
        """Test that whitespace is preserved in names."""
        aliases = Aliases(
            {
                "spaced": ["some name", "some  name"],
            }
        )
        assert aliases.normalize("some name") == "some name"
        assert aliases.normalize("SOME NAME") == "some name"

    def test_key_not_in_alias_list(self):
        """Test when the dictionary key is not in its own alias list."""
        aliases = Aliases(
            {
                "code_name": ["canonical_form", "variant1", "variant2"],
            }
        )
        # The key "code_name" is not in the alias list
        assert aliases.normalize("canonical_form") == "canonical_form"
        assert aliases.normalize("variant1") == "canonical_form"
        # Key itself is not an alias and should raise
        with pytest.raises(
            UnrecognizedAliasError, match="'code_name' not found in aliases"
        ):
            aliases.normalize("code_name")


class TestAliasesIntegration:
    def test_round_trip_normalization(self, aliases):
        """Test that normalizing any variant gives consistent results."""
        variants = ["dark", "darks", "DARK", "DARKS", "Dark"]
        canonical = "dark"

        for variant in variants:
            assert aliases.normalize(variant) == canonical

    def test_all_aliases_map_to_canonical(self, aliases):
        """Test that all aliases in each list map to the canonical form."""
        for _key, alias_list in aliases.alias_dict.items():
            if not alias_list:
                continue
            canonical = alias_list[0]
            for alias in alias_list:
                assert aliases.normalize(alias) == canonical

    def test_toml_structure_example(self):
        """Test with a structure exactly as it appears in TOML."""
        toml_aliases = {
            "dark": ["dark", "darks"],
            "flat": ["flat", "flats"],
            "bias": ["bias", "biases"],
            "fits": ["fits", "fit"],
            "SiiOiii": ["SiiOiii", "SII-OIII", "S2-O3"],
            "HaOiii": ["HaOiii", "HA-OIII", "Halpha-O3"],
        }

        aliases = Aliases(toml_aliases)

        # Test frame types
        assert aliases.normalize("darks") == "dark"
        assert aliases.normalize("FLAT") == "flat"
        assert aliases.normalize("biases") == "bias"

        # Test file suffixes
        assert aliases.normalize("fit") == "fits"

        # Test filter names
        assert aliases.normalize("SII-OIII") == "SiiOiii"
        assert aliases.normalize("HA-OIII") == "HaOiii"
        assert aliases.normalize("Halpha-O3") == "HaOiii"
