; --- Definitions ---

; Class declaration
(class_declaration
  name: (identifier) @name.definition.class)

; Method declaration
(method_declaration
  name: (identifier) @name.definition.method)

; Constructor declaration
(constructor_declaration
  name: (identifier) @name.definition.method)

; Interface declaration
(interface_declaration
  name: (identifier) @name.definition.interface)

; Enum declaration
(enum_declaration
  name: (identifier) @name.definition.enum)

; --- References ---

; import com.example.Foo
(import_declaration
  (scoped_identifier) @name.reference.import)

; Class extends
(class_declaration
  (superclass
    (type_identifier) @name.reference.inherit))

; Class implements
(class_declaration
  (super_interfaces
    (type_list
      (type_identifier) @name.reference.implement)))
