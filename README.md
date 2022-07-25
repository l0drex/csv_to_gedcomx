This is a simple python script that can convert two CSV tables to a GedcomX json file.

# Basic usage

_Example:_
```shell
# print result to stdout
main.py persons.csv families.csv
# put result in new file named output.json
main.py persons.csv families.csv --output output.json
```

Replace the file names with your own. 

# Structure of the CSV files

## Person table

| id  | title | surname | middle_name | born  | married | nickname | aka | full_name  | gender   | child_of | birth_date           | birth_place | death_date  | death_place | death_cause  | occupation             | religion                 | notes                    |
|-----|-------|---------|-------------|-------|---------|----------|-----|------------|----------|----------|----------------------|-------------|-------------|-------------|--------------|------------------------|--------------------------|--------------------------|
| 0   |       |         |             |       |         |          |     | unknown    | Unknown  |          |                      |             |             |             |              |                        |                          | _reserved_               |
| 1   | Prof. | John    |             | Doe   |         | Jonny    |     | John Doe   | Male     |          | +1919-01-09          | Dirmingcan  | +2010-10-10 | Brolin      |              | professional describer | flying spaghetti monster | _cause of death missing_ |
| 2   |       | Miriam  | Alex        | Smith | Doe     |          |     | Miriam Doe | Female   |          | +1902-02-02          | Ohoho       | +2003-03-03 | Brolin      | heart attack | example giver          |
| 3   |       |         |             | Doe   |         |          |     | Kim Doe    | Intersex | 0        | +2001-02-01T06-08-02 | Brolin      |

Notes:
- The ID `0` is reserved️ for the unknown person. It can be used in families with unknown partners. Anything specified for that ID will be ignored.
- IDs can be any string (except for `0`). They are directly used in the resulting GedcomX file
- `full_name` is the name the person normally is called
- `gender` can be `Male`, `Female`, `Unknown` or `Intersex`
- dates are formatted as specified [here](https://github.com/FamilySearch/gedcomx/blob/master/specifications/date-format-specification.md)
- `child_of` specifies the family id that this person is a child of. It must be included in the family table
- `notes` are seperated by semicolon

## Family table

| id  | partner1 | partner2 | date     | place  | notes                                               |
|-----|----------|----------|----------|--------|-----------------------------------------------------|
| 0   | 1        | 0        | +1940-04 | Brolin | family of Kim                                       |
| 1   | 2        | 0        | +1920    |        | since partner2 is 0, a new person will be generated |

- `ID` can be any string, `0` is not reserved
- `partner1` and `partner2` are IDs of persons specified in the person table
- `date` is the date of the marriage, `place` is the place of the marriage
- `notes` are seperated by semicolon
