import argparse
import csv
import datetime
import json
from typing import Optional

from gedcomx import models, enums

# maps relationship ids to person ids
children: dict[str, [str]] = {}
root = models.GedcomXObject()


def main(args) -> Optional[dict]:
    root.persons = []
    root.relationships = []

    with open(args.persons) as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row['id'] == '0':
                continue
            if row['id'] == '':
                break

            root.persons.append(parse_person(row))

    with open(args.families) as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row['id'] == '':
                break

            root.relationships.append(parse_family(row))

    min_generation = -min(add_generations(root.persons[0], 0))
    # add generation to partners of siblings and others who are not reached
    not_reached = (p for p in root.persons
                   # if no generation defined
                   if len([f for f in p.facts if f.type == enums.FactType.generationNumber]) == 0)
    for person in not_reached:
        partner = next(
            # partner is the other person
            find_person_by_id(r.person1 if r.person2.resource[1:] == person.id else r.person2)
            # of a couple relationship
            for r in root.relationships if r.type == enums.RelationshipType.couple
            # that contains the person
            and person.id in [r.person1.resource[1:], r.person2.resource[1:]])
        try:
            partner_generation: models.Fact = next(
                f for f in partner.facts if f.type == enums.FactType.generationNumber)
            new_min = -min(add_generations(person, int(partner_generation.value)))
            if new_min > min_generation:
                min_generation = new_min
        except StopIteration:
            print(f'{person.id} is not connected!')

    generation_start = min_generation  # 0 + min_generation
    try:
        age_start = get_age(root.persons[0])
    except ValueError:
        age_start = 0
    # adjust generation value, so that the oldest person is the lowest generation while not being negative
    for person in root.persons:
        try:
            generation_fact: models.Fact = next(f for f in person.facts if f.type == enums.FactType.generationNumber)
            generation = int(generation_fact.value) + min_generation
            generation_fact.value = str(generation)

            is_dead = len([f for f in person.facts if f.type == enums.FactType.death]) > 0
            if not is_dead:
                # estimating age, assuming each generation is 25 years apart
                if (generation_start - generation) * 25 + age_start > 120:
                    person.facts.append(models.Fact(type=enums.FactType.death))
        except StopIteration:
            pass

    if args.output:
        with open(args.output, "w") as file:
            json.dump(root.dict(), file)
        return

    return root.dict(exclude_none=True, exclude_defaults=True)


def parse_person(row) -> models.Person:
    person = models.Person(
        id=row['id'],
        gender=models.Gender(type=f'http://gedcomx.org/{row["gender"]}'),
        names=get_names(row),
        facts=[models.Fact(type=enums.FactType.maritalStatus, value='single')],
        private=False
    )
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

    if row['death_date'] or row['death_place'] or row['cause_of_death'] or too_old:
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
    """Parses a row specifying a person to a GedcomX name"""

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
        yield models.Name(type=enums.NameType.marriedName, nameForms=[models.NameForm(fullText=row['married'])])

    if row['born']:
        yield models.Name(type=enums.NameType.birthName, nameForms=[models.NameForm(fullText=row['born'])])

    if row['nickname']:
        yield models.Name(type=enums.NameType.nickname, nameForms=[models.NameForm(fullText=row['nickname'])])

    if row['aka']:
        yield models.Name(type=enums.NameType.alsoKnownAs, nameForms=[models.NameForm(fullText=row['aka'])])


def parse_family(row) -> models.Relationship:
    """Parses a row representing a family and returns a GedcomX relationship"""
    relationship = models.Relationship(
        id='r-' + row['id'],
        person1=models.ResourceReference(resource='#' + row['partner1']),
        person2=models.ResourceReference(resource='#' + row['partner2']),
        type=enums.RelationshipType.couple.value,
        facts=[models.Fact(
            type=enums.CoupleRelationshipFactType.numberOfChildren,
            value=len(children[row['id']]) if row['id'] in children else 0)
        ]
    )

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
        try:
            person = find_person_by_id(person_id)
        except ReferenceError:
            person_id = models.ResourceReference(resource=f'#{len(root.persons)}')
            person = models.Person(id=len(root.persons),
                                   facts=[models.Fact(type=enums.FactType.maritalStatus, value='single')])
            root.persons.append(person)

        marital_status = [f for f in person.facts if f.type == enums.FactType.maritalStatus][0]
        marital_status.value = 'married'
        if row['date']:
            # add date and age qualifier
            marital_status.date = models.Date(formal=row['date'])
            try:
                age = get_age(person, marital_status.date)
                marital_status.qualifiers = [models.Qualifier(name='http://gedcomx.org/Age', value=age)]
            except ValueError as e:
                print(f"Error while parsing age at marriage of {person.id}:", e)

        # add parent-child
        if row['id'] in children:
            for child_id in children[row['id']]:
                root.relationships.append(models.Relationship(
                    id=f'r-{person_id}-{child_id}',
                    type=enums.RelationshipType.parentChild,
                    person1=person_id,
                    person2=models.ResourceReference(resource='#' + child_id)))

    return relationship


def get_age(person: models.Person, date: models.Date = None) -> Optional[int]:
    """Calculates the age of a person at a date
    :param person: person whose age shall be calculated
    :param date: current date if not specified
    """

    birth = [f for f in person.facts if f.type == enums.FactType.birth]
    if len(birth) <= 0:
        raise ValueError('Birth is unknown')
    birth = birth[0]
    if not birth.date or not birth.date.formal:
        raise ValueError('Birth is unknown')
    birthday = date_to_python_date(birth.date)
    date_parsed = date_to_python_date(date) if date else datetime.date.today()

    age = (date_parsed - birthday).days // 365
    if age < 0:
        raise ValueError("Event happened before birth!")
    return age


def date_to_python_date(date: models.Date) -> datetime.date:
    """Converts a date to a python date object
    :param date GedcomX date with formal specified
    """
    formal_date = date.formal
    if len(formal_date) <= 5:
        # +YYYY
        formal_date += '-01'
    if len(formal_date) <= 8:
        # +YYYY-MM
        formal_date += '-01'

    return datetime.date.fromisoformat(formal_date[1:])


def add_generations(person, generation: int) -> [int]:
    # first, check if a generation is already defined
    try:
        next(f for f in person.facts if f.type == enums.FactType.generationNumber)
        return
    except StopIteration:
        pass

    person.facts.append(models.Fact(type=enums.FactType.generationNumber, value=str(generation)))
    parent_ids = (r.person1 for r in root.relationships
                  if r.type == enums.RelationshipType.parentChild and r.person2.resource[1:] == person.id)
    for parent_id in parent_ids:
        parent = find_person_by_id(parent_id)
        yield from add_generations(parent, generation - 1)

    child_ids = (r.person2 for r in root.relationships
                 if r.type == enums.RelationshipType.parentChild and r.person1.resource[1:] == person.id)
    for child_id in child_ids:
        child = find_person_by_id(child_id)
        yield from add_generations(child, generation + 1)

    yield generation


def find_person_by_id(person_id):
    if isinstance(person_id, models.ResourceReference):
        person_id = person_id.resource[1:]
    try:
        return next(p for p in root.persons if p.id == person_id)
    except StopIteration:
        raise ReferenceError(f'No person with id {person_id} could be found')


parser = argparse.ArgumentParser(
    prog='CSV-GedcomX Converter',
    description='Converts two CSV files to one GedcomX file in JSON format')
parser.add_argument('persons', help='Path to CSV table containing the persons')
parser.add_argument('families', help='Path to CSV table containing the families')
parser.add_argument('--output', help='Path to output file')

if __name__ == '__main__':
    result = main(parser.parse_args())
    if result:
        print(json.dumps(result))
