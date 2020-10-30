

# check_row cycles through entire row to ensure uniqueness in the new_value within that row
# @param grid is a list made up of row lists (2D list). Each row list is made up of integers
# @param y_cord is an index pointing to a row list (Y coordinate of the 2D array)
# @param new_value is a randomly generated integer
def check_row(grid, y_cord, new_value):
    for x_cord in range(9):
        if grid[y_cord][x_cord] == new_value:
            return False
    return True


# check_col cycles through entire column to ensure uniqueness of new_value within that column
# @param grid is a list made up of row lists (2D list). Each row list is made up of integers
# @param x_cord is an index within a row list (X coordinate of the 2D array)
# @param new_value is a randomly generated integer
def check_col(grid, x_cord, new_value):
    for y_cord in range(9):
        if grid[y_cord][x_cord] == new_value:
            return False
    return True
