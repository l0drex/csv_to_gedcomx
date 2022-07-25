import datetime
from typing import Optional

from gedcomx import models, enums


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


def find_person_by_id(root: models.GedcomXObject, person_id):
    if isinstance(person_id, models.ResourceReference):
        person_id = person_id.resource[1:]
    try:
        return next(p for p in root.persons if p.id == person_id)
    except StopIteration:
        raise ReferenceError(f'No person with id {person_id} could be found')


def add_generations(root: models.GedcomXObject):
    min_generation = -min(add_generations_recursive(root, root.persons[0], 0))
    # add generation to partners of siblings and others who are not reached
    not_reached = (p for p in root.persons
                   # if no generation defined
                   if len([f for f in p.facts if f.type == enums.FactType.generationNumber]) == 0)
    for person in not_reached:
        partner = next(
            # partner is the other person
            find_person_by_id(root, r.person1 if r.person2.resource[1:] == person.id else r.person2)
            # of a couple relationship
            for r in root.relationships if r.type == enums.RelationshipType.couple
            # that contains the person
            and person.id in [r.person1.resource[1:], r.person2.resource[1:]])
        try:
            partner_generation: models.Fact = next(
                f for f in partner.facts if f.type == enums.FactType.generationNumber)
            new_min = -min(add_generations_recursive(root, person, int(partner_generation.value)))
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


def add_generations_recursive(root: models.GedcomXObject, person: models.Person, generation: int) -> [int]:
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
        parent = find_person_by_id(root, parent_id)
        yield from add_generations_recursive(root, parent, generation - 1)

    child_ids = (r.person2 for r in root.relationships
                 if r.type == enums.RelationshipType.parentChild and r.person1.resource[1:] == person.id)
    for child_id in child_ids:
        child = find_person_by_id(root, child_id)
        yield from add_generations_recursive(root, child, generation + 1)

    yield generation
