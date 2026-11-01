(list_lit . (sym_lit name: (sym_name) @_head) . (sym_lit name: (sym_name) @name) (#match? @_head "{{def_heads}}")) @definition.def
(sym_lit) @reference
(comment) @comment
(list_lit . (sym_lit name: (sym_name) @_ns) (#eq? @_ns "ns")) @import
