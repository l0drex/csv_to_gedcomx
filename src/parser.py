import csv
import logging
from urllib.error import URLError

from urllib.parse import urlparse
from urllib.request import urlopen

from fuzzywuzzy import fuzz
from gedcomx import models, enums
from gedcomx.models import SourceReference, SourceDescription, SourceCitation

from utils import get_age, find_person_by_id, check_date, check_living

# maps relationship ids to person ids
children: dict[str, [str]] = {}
# used to identify possible spelling mistakes
last_names: set[str] = set()
sources: {str: SourceReference} = {}


def load_data(person_file: str, family_file: str) -> models.GedcomXObject:
    """
    Loads the csv data from the specified file paths
    :param person_file: path to a csv file containing info about persons
    :param family_file: path to a csv file containing info about relationships
    :return: the root object of the GedcomX file
    """

    root = models.GedcomXObject(persons=[], relationships=[], sourceDescriptions=[])
    with open(person_file) as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row['id'] == '0':
                continue
            if row['id'] == '':
                break

            root.persons.append(parse_person(root, row))
            if row['media'] != '':
                root.sourceDescriptions.append(add_media(row))

    with open(family_file) as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row['id'] == '':
                break

            root.relationships.append(parse_family(root, row))

    return root


def parse_person(root, row) -> models.Person:
    """
    Utility function that parses a single row of person data
    :param root: document root
    :param row: the row returned by the dict reader
    :return: a GedcomX person
    """

    person = models.Person(
        id=f'p-{row["id"]}',
        gender=models.Gender(type=f'http://gedcomx.org/{row["gender"] if row["gender"] else "Unknown"}'),
        names=get_names(row),
        facts=[models.Fact(type=enums.FactType.maritalStatus, value='Single')],
        private=False
    )
    if row['notes']:
        person.notes = [models.Note(text=note) for note in row['notes'].split(';')]
    if row['source']:
        src = row['source']
        if src not in sources:
            root.sourceDescriptions.append(
                SourceDescription(citations=[SourceCitation(value=src)], id=f's-{row["id"]}')
            )
            sources[src] = SourceReference(description=f'#s-{row["id"]}')

        ref = sources[src]
        person.sources = [ref]

    if row['birth_date'] or row['birth_place']:
        check_date(row['birth_date'], 'p-' + row['id'])
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
        check_date(row['death_date'], 'p-' + row['id'])
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

    if row['media']:
        source_reference = SourceReference(description=f'#i-{row["id"]}')
        person.media = [source_reference]

    if row['confidence']:
        person.confidence = 'http://gedcomx.org/' + row['confidence']

    return person


def get_names(row) -> list[models.Name]:
    """
    Parses a row specifying a person to a GedcomX name
    :param row: A single row defining a person, as returned by the dict reader
    :return: list of GedcomX names
    """

    # collect name parts
    title = models.NamePart(value=row['title'], type=enums.NamePartType.prefix)
    title.qualifiers = [models.Qualifier(name='http://gedcomx.org/Title')]

    given_name = models.NamePart(value=row['given_name'], type=enums.NamePartType.given)
    given_name.qualifiers = [models.Qualifier(name='http://gedcomx.org/Primary')]

    middle_name = models.NamePart(value=row['middle_name'], type=enums.NamePartType.given)
    middle_name.qualifiers = [models.Qualifier(name='http://gedcomx.org/Middle')]

    nickname = models.NamePart(value=row['nickname'], type=enums.NamePartType.given)
    nickname.qualifiers = [models.Qualifier(name='http://gedcomx.org/Secondary')]

    aka = models.NamePart(value=row['aka'], type=enums.NamePartType.given)

    check_last_name(row['surname_born'], row['id'])
    surname_born = models.NamePart(value=row['surname_born'], type=enums.NamePartType.surname)
    surname_born.qualifiers = [models.Qualifier(name='http://gedcomx.org/Family')]

    check_last_name(row['surname_married'], row['id'])
    surname_married = models.NamePart(value=row['surname_married'], type=enums.NamePartType.surname)
    surname_married.qualifiers = [models.Qualifier(name='http://gedcomx.org/Family')]

    if row['surname_married']:
        name_parts = [p for p in [title, given_name, middle_name, surname_married] if p.value != '']
        yield models.Name(type=enums.NameType.marriedName, nameForms=[
            models.NameForm(
                fullText=row['full_name'],
                parts=name_parts)
        ])

    if row['surname_born']:
        name_parts = [p for p in [title, given_name, middle_name, surname_born] if p.value != '']
        name_form = models.NameForm(parts=name_parts)
        if not row['surname_married']:
            name_form.fullText = row['full_name']

        yield models.Name(type=enums.NameType.birthName, nameForms=[
            name_form
        ])

    if row['nickname']:
        name_parts = [p for p in [nickname] if p.value != '']
        yield models.Name(type=enums.NameType.nickname, nameForms=[
            models.NameForm(
                fullText=row['full_name'],
                parts=name_parts)
        ])

    if row['aka']:
        name_parts = [p for p in [aka] if p.value != '']
        yield models.Name(type=enums.NameType.alsoKnownAs, nameForms=[
            models.NameForm(
                fullText=row['full_name'],
                parts=name_parts)
        ])

def check_last_name(name: str, person_id: str):
    if name not in last_names:
        # search for spelling mistakes
        for present_name in last_names:
            hamming_distance = fuzz.ratio(list(name), list(present_name))
            if hamming_distance > 92:
                logging.warning(f'Possible spelling mistake found: {name} of {person_id} could be {present_name}')
        last_names.add(name)


def replace_if_unknown(root: models.GedcomXObject, p: str) -> [models.GedcomXObject, str]:
    if p == '0':
        # add new person if undefined
        p = f'p-{len(root.persons) + 1}'
        person = models.Person(
            id=p,
            facts=[models.Fact(type=enums.FactType.maritalStatus, value='Single')],
            gender=models.Gender(type=enums.GenderType.unknown))
        root.persons.append(person)
    else:
        p = f'p-{p}'
    return root, p


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
            check_date(row['date'], 'r-' + row['id'])
            marriage.date = models.Date(formal=row['date'])
        if row['place']:
            marriage.place = models.PlaceReference(original=row['place'])
        relationship.facts.append(marriage)
    # add new facts to the persons
    for person_id in [relationship.person1, relationship.person2]:
        person = find_person_by_id(root, person_id)

        marital_status = [f for f in person.facts if f.type == enums.FactType.maritalStatus][0]
        marital_status.value = 'Married'
        if row['date']:
            # add date and age qualifier
            marital_status.date = models.Date(formal=row['date'])
            try:
                if not check_living(person, marital_status.date):
                    logging.error(f'Person {person_id} was not alive at time of their marriage!')
                else:
                    age = get_age(person, marital_status.date)
                    if age > 50:
                        logging.warning(f'Person {person_id} was over 50 years old at time of marriage!')
                    marital_status.qualifiers = [models.Qualifier(name='http://gedcomx.org/Age', value=age)]
            except ValueError as e:
                logging.warning(f'Could not determine age at marriage of {person.id}: {e}')

        # add parent-child
        if row['id'] in children:
            for child_id in children[row['id']]:
                root.relationships.append(models.Relationship(
                    id=f'r-{person_id.resource[1:]}-p-{child_id}',
                    type=enums.RelationshipType.parentChild,
                    person1=person_id,
                    person2=models.ResourceReference(resource='#p-' + child_id)))

    return relationship


def add_media(row) -> models.SourceDescription:
    # add a media reference
    url = row['media']
    host = urlparse(url).hostname
    citation = SourceCitation(value=host)
    source_description = SourceDescription(citations=[citation])
    source_description.id = f'i-{row["id"]}'
    source_description.about = url
    source_description.resourceType = enums.ResourceType.digitalArtifact

    try:
        with urlopen(url) as response:
            info = response.info()
            source_description.mediaType = info.get_content_type()
    except URLError as e:
        logging.error(f'Resource unavailable: {url}')
        logging.error(e)

    return source_description
