from rest_framework.exceptions import ErrorDetail, ValidationError


def field_error(field, code, message="Invalid."):
    """A ValidationError whose body is {errors: {field: [{message, code}]}}.

    (Passing {"message":..,"code":..} dicts inside the list does NOT work: DRF would
    wrap each value separately and the code would be lost.)
    """
    return ValidationError({field: [ErrorDetail(message, code=code)]})
