# TOML Import Examples

This directory demonstrates the TOML import feature in starbash, which allows you to reuse and inherit configuration blocks across different TOML files.

## What are TOML imports?

TOML imports let you define configuration once and reuse it in multiple places, reducing duplication and making recipes easier to maintain. This is especially useful for stage definitions where many stages share common settings but differ only in their scripts.

## Import Syntax

```toml
[target_node.import]
node = "source.node.path"  # required: dot-separated path to the node to import
file = "path/to/file.toml" # optional: source file (default: current file)
repo = "url_or_path"       # optional: source repo (default: current repo)
```

## Examples in this Directory

- `library.toml` - A library file with reusable stage templates
- `simple-import.toml` - Importing from the same file
- `cross-file-import.toml` - Importing from a different file
- `stage-inheritance.toml` - Practical example of stage template reuse
- `array-import.toml` - Using imports within array-of-tables

## How it Works

1. When a Repo is loaded, it recursively scans for `import` keys
2. For each import, it loads the referenced node from the specified file/repo
3. The import key is replaced with a deep copy of the imported content
4. Imported files are cached to avoid redundant reads
5. The imported content is "monkey-patched" to include its source repo

## Use Cases

### Stage Template Reuse

Define a base stage configuration once and reuse it with minor variations:

```toml
# Base template
[base_siril_stage]
tool = "siril"
input.source = "repo"
input.required = 2
context.mode = "standard"

# Reuse with different script
[recipe.stage.calibrate.import]
node = "base_siril_stage"

[recipe.stage.calibrate]
script = "calibrate {light_base} -bias={master['bias']}"
```

### Cross-Repository Sharing

Import common configurations from shared library repositories:

```toml
[my_stage.import]
repo = "file:///path/to/shared/library"
node = "common.preprocessing"
```

### Nested Imports

Imports can reference content that itself contains imports, creating inheritance chains:

```toml
# foundation.toml
[base]
tool = "siril"

# intermediate.toml
[extended.import]
file = "foundation.toml"
node = "base"

# main.toml
[final.import]
file = "intermediate.toml"
node = "extended"
```

## Limitations

- Cannot import at the root level of a TOML file
- Import keys must be tables (dictionaries), not arrays or simple values
- When using imports in array-of-tables, the import merges into the existing table (preserving other keys)
- Files that use imports cannot be reliably rewritten (the import syntax is lost after resolution)

## Best Practices

1. **Create library files** for commonly-used configurations
2. **Use relative paths** when importing from files in the same repo
3. **Provide descriptive node names** that indicate what the template is for
4. **Keep imports shallow** - deep inheritance chains can be hard to understand
5. **Document your templates** with comments explaining their purpose and expected customizations
