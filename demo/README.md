# Demo files

`grupo_con_errores.xlsx`: 9 fictitious students, 5 valid and 4 invalid, to show how the import reports rejected rows.
Import it in `/admin` → *Crear grupo desde Excel* (partial mode). Expected result: 9 rows read, 5 created, 4 rejected:

| Excel row | Student ID | Reason |
|---|---|---|
| 5 | D0004 | `D0004: calificacion invalida: 150.0 (debe ser un numero entre 0 y 100)` |
| 6 | D0005 | `parcial1: 'abc' no es un numero` |
| 8 | D0007 | `nombre vacio` |
| 10 | D0003 | repeated ID in the file |

Delete the group afterwards from the admin panel. Nothing here is real student data.
