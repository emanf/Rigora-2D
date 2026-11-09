"""Shared double-precision affine math using column vectors and screen-space rotations."""

import math

from rigora.domain.validation import ProjectError

type Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)


def affine(
    x: float,
    y: float,
    rotation: float,
    scale_x: float,
    scale_y: float,
    pivot_x: float,
    pivot_y: float,
) -> Matrix:
    """Compose translation, pivot, clockwise rotation, scale and inverse pivot."""
    angle = math.radians(rotation)
    a, b = math.cos(angle) * scale_x, math.sin(angle) * scale_x
    c, d = -math.sin(angle) * scale_y, math.cos(angle) * scale_y
    return (
        a,
        b,
        c,
        d,
        x + pivot_x - a * pivot_x - c * pivot_y,
        y + pivot_y - b * pivot_x - d * pivot_y,
    )


def multiply(parent: Matrix, local: Matrix) -> Matrix:
    """Compose a child local matrix beneath its parent's world matrix."""
    a, b, c, d, tx, ty = parent
    e, f, g, h, ux, uy = local
    return (
        a * e + c * f,
        b * e + d * f,
        a * g + c * h,
        b * g + d * h,
        a * ux + c * uy + tx,
        b * ux + d * uy + ty,
    )


def transform_point(matrix: Matrix, x: float, y: float) -> tuple[float, float]:
    """Map a local point through an affine transform."""
    a, b, c, d, tx, ty = matrix
    return a * x + c * y + tx, b * x + d * y + ty


def inverse(matrix: Matrix) -> Matrix:
    """Invert a finite nonsingular affine matrix or report an unsafe editing space."""
    a, b, c, d, x, y = matrix
    determinant = a * d - b * c
    if not math.isfinite(determinant) or abs(determinant) < 1e-12:
        raise ProjectError("Cannot edit in a singular or numerically unstable parent space.")
    result = (d / determinant, -b / determinant, -c / determinant, a / determinant)
    e, f, g, h = result
    return (*result, -e * x - g * y, -f * x - h * y)


def decompose(matrix: Matrix, pivot_x: float = 0, pivot_y: float = 0) -> tuple[float, ...]:
    """Recover TRS components while rejecting shear that the authoring model cannot express."""
    a, b, c, d, tx, ty = matrix
    sx = math.hypot(a, b)
    if sx > 1e-12:
        rotation = math.atan2(b, a)
        sy = (a * d - b * c) / sx
        if abs(a * c + b * d) > 1e-8 * max(1, sx * math.hypot(c, d)):
            raise ProjectError("This parent change would require shear; use uniform parent scales.")
    else:
        rotation, sy = math.atan2(-c, d), math.hypot(c, d)
    values = (
        tx - pivot_x + a * pivot_x + c * pivot_y,
        ty - pivot_y + b * pivot_x + d * pivot_y,
        math.degrees(rotation),
        sx,
        sy,
        pivot_x,
        pivot_y,
    )
    if not all(math.isfinite(value) for value in values):
        raise ProjectError("Transform exceeds the finite geometry range.")
    return values
