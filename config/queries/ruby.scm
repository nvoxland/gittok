(method name: (identifier) @name) @definition.method
(singleton_method name: (identifier) @name) @definition.method
(class name: (constant) @name) @definition.class
(module name: (constant) @name) @definition.class
[(identifier) (constant)] @reference
(comment) @comment
(call method: (identifier) @_m arguments: (argument_list . (string (string_content) @import.path)) (#eq? @_m "require")) @import
(call method: (identifier) @import.relative arguments: (argument_list . (string (string_content) @import.path)) (#eq? @import.relative "require_relative")) @import
