; --- Definitions ---

; Top-level function
(function_definition
  name: (identifier) @name.definition.function)

; Method inside a class
(class_definition
  body: (block
    (function_definition
      name: (identifier) @name.definition.method)))

; Class
(class_definition
  name: (identifier) @name.definition.class)

; Top-level assignment (constants/variables)
(module
  (assignment
    left: (identifier) @name.definition.variable))

; --- References ---

; import foo
(import_statement
  name: (dotted_name) @name.reference.import)

; from foo import bar
(import_from_statement
  module_name: (dotted_name) @name.reference.import)

; Class inheritance: class X(Base)
(class_definition
  superclasses: (argument_list
    (identifier) @name.reference.inherit))
