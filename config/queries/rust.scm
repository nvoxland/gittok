(function_item name: (identifier) @name) @definition.function
(struct_item name: (type_identifier) @name) @definition.class
(enum_item name: (type_identifier) @name) @definition.type
(trait_item name: (type_identifier) @name) @definition.interface
[(identifier) (type_identifier) (field_identifier)] @reference
[(line_comment) (block_comment)] @comment
(use_declaration argument: (_) @import.path) @import
