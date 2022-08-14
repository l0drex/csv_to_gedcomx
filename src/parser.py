import csv

from fuzzywuzzy import fuzz
from gedcomx import models, enums

from utils import get_age, find_person_by_id

# maps relationship ids to person ids
children: dict[str, [str]] = {}
# used to identify possible spelling mistakes
last_names: set[str] = set()


def load_data(person_file: str, family_file: str) -> models.GedcomXObject:
    """
    Loads the csv data from the specified file paths
    :param person_file: path to a csv file containing info about persons
    :param family_file: path to a csv file containing info about relationships
    :return: the root object of the GedcomX file
    """

    root = models.GedcomXObject(persons=[], relationships=[])
    with open(person_file) as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row['id'] == '0':
                continue
            if row['id'] == '':
                break

            root.persons.append(parse_person(row))

    with open(family_file) as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row['id'] == '':
                break

            root.relationships.append(parse_family(root, row))

    return root


def parse_person(row) -> models.Person:
    """
    Utility function that parses a single row of person data
    :param row: the row returned by the dict reader
    :return: a GedcomX person
    """

    person = models.Person(
        id=row['id'],
        gender=models.Gender(type=f'http://gedcomx.org/{row["gender"]}'),
        names=get_names(row),
        facts=[models.Fact(type=enums.FactType.maritalStatus, value='single')],
        private=False
    )
    if row['notes']:
        person.notes = [models.Note(text=note) for note in row['notes'].split(';')]

    if row['birth_date'] or row['birth_place']:
        birth = models.Fact(
            type=enums.FactType.birth,
            date=models.Date(formal=row['birth_date']) if row['birth_date'] else None,
            place=models.PlaceReference(original=row['birth_place']) if row['birth_place'] else None
        )
        person.facts.append(birth)

    try:
        too_old = get_age(person) > 120
    except ValueError:
        too_old = False

    if row['death_date'] or row['death_place'] or row['death_cause'] or too_old:
        death = models.Fact(
            type=enums.FactType.death,
            date=models.Date(formal=row['death_date']) if row['death_date'] else None,
            place=models.PlaceReference(original=row['death_place']) if row['death_place'] else None,
        )
        death.qualifiers = [f for f in [
            models.Qualifier(
                name='http://gedcomx.org/Age',
                value=get_age(person, models.Date(formal=row['death_date']))
            ) if row['death_date'] else None,
            models.Qualifier(
                name='http://gedcomx.org/Cause',
                value=row['death_cause']
            ) if row['death_cause'] else None] if f is not None]
        if len(death.qualifiers) == 0:
            death.qualifiers = None
        person.facts.append(death)
    if row['religion']:
        religion = models.Fact(
            type=enums.FactType.religion,
            value=row['religion'])
        person.facts.append(religion)
    if row['occupation']:
        occupation = models.Fact(
            type=enums.FactType.occupation,
            value=row['occupation'])
        person.facts.append(occupation)

    # collect children
    if row['child_of'] in children:
        children[row['child_of']].append(row['id'])
    else:
        children[row['child_of']] = [row['id']]

    return person


def get_names(row) -> list[models.Name]:
    """
    Parses a row specifying a person to a GedcomX name
    :param row: A single row defining a person, as returned by the dict reader
    :return: list of GedcomX names
    """

    # first, build a default name containing everything
    formal_name_forms = models.NameForm(fullText=row['full_name'], parts=[])
    if row['title']:
        title = models.NamePart(value=row['title'])
        title.qualifiers = [models.Qualifier(name='http://gedcomx.org/Title')]
        formal_name_forms.parts.append(title)
    surname = models.NamePart(type=enums.NamePartType.surname, value=row['surname'])
    surname.qualifiers = [models.Qualifier(name=enums.IdentifierType.primary)]
    formal_name_forms.parts.append(surname)
    if row['middle_name']:
        middle_name = models.NamePart(value=row['middle_name'])
        middle_name.qualifiers = [models.Qualifier(name='http://gedcomx.org/Middle')]
        formal_name_forms.parts.append(middle_name)
    last_name = models.NamePart(value=row['married'] if row['married'] else row['born'])
    last_name.qualifiers = [models.Qualifier(name='http://gedcomx.org/Family')]
    formal_name_forms.parts.append(last_name)
    yield models.Name(nameForms=[formal_name_forms])

    # then give some additional names
    if row['married']:
        check_last_name(row['married'], row['id'])
        yield models.Name(type=enums.NameType.marriedName, nameForms=[models.NameForm(fullText=row['married'])])

    if row['born']:
        check_last_name(row['born'], row['id'])
        yield models.Name(type=enums.NameType.birthName, nameForms=[models.NameForm(fullText=row['born'])])

    if row['nickname']:
        yield models.Name(type=enums.NameType.nickname, nameForms=[models.NameForm(fullText=row['nickname'])])

    if row['aka']:
        yield models.Name(type=enums.NameType.alsoKnownAs, nameForms=[models.NameForm(fullText=row['aka'])])


def check_last_name(name: str, person_id: str):
    if name not in last_names:
        # search for spelling mistakes
        for present_name in last_names:
            hamming_distance = fuzz.ratio(list(name), list(present_name))
            if hamming_distance > 92:
                print(f"Possible spelling mistake found: {name} of {person_id} should be {present_name}")
        last_names.add(name)


def replace_if_unknown(root, partner1):
    if partner1 == '0':
        # add new person if undefined
        partner1 = str(len(root.persons) + 1)
        person = models.Person(id=partner1,
                               facts=[models.Fact(type=enums.FactType.maritalStatus, value='single')],
                               gender=models.Gender(type=enums.GenderType.unknown))
        root.persons.append(person)
    return root, partner1


def parse_family(root: models.GedcomXObject, row) -> models.Relationship:
    """
    Parses single a row representing a family and returns a GedcomX relationship
    :param root: the root of the GedcomX file
    :param row: a single row of family data, as returned by the dict reader
    :return: a GedcomX relationship
    """

    root, partner1 = replace_if_unknown(root, row['partner1'])
    root, partner2 = replace_if_unknown(root, row['partner2'])

    relationship = models.Relationship(
        id='r-' + row['id'],
        person1=models.ResourceReference(resource='#' + partner1),
        person2=models.ResourceReference(resource='#' + partner2),
        type=enums.RelationshipType.couple.value,
        facts=[models.Fact(
            type=enums.CoupleRelationshipFactType.numberOfChildren,
            value=len(children[row['id']]) if row['id'] in children else 0)
        ]
    )
    if row['notes']:
        relationship.notes = [models.Note(text=note) for note in row['notes'].split(';')]

    # add date and place if present
    if row['date'] or row['place']:
        marriage = models.Fact(type=enums.CoupleRelationshipFactType.marriage)
        if row['date']:
            marriage.date = models.Date(formal=row['date'])
        if row['place']:
            marriage.place = models.PlaceReference(original=row['place'])
        relationship.facts.append(marriage)
    # add new facts to the persons
    for person_id in [relationship.person1, relationship.person2]:
        person = find_person_by_id(root, person_id)

        marital_status = [f for f in person.facts if f.type == enums.FactType.maritalStatus][0]
        marital_status.value = 'married'
        if row['date']:
            # add date and age qualifier
            marital_status.date = models.Date(formal=row['date'])
            try:
                age = get_age(person, marital_status.date)
                marital_status.qualifiers = [models.Qualifier(name='http://gedcomx.org/Age', value=age)]
            except ValueError as e:
                print(f"Could not determine age at marriage of {person.id}:", e)

        # add parent-child
        if row['id'] in children:
            for child_id in children[row['id']]:
                root.relationships.append(models.Relationship(
                    id=f'r-{person_id}-{child_id}',
                    type=enums.RelationshipType.parentChild,
                    person1=person_id,
                    person2=models.ResourceReference(resource='#' + child_id)))

    return relationship
