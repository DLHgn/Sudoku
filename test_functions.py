

# depreciated. Keeping for now in case it's needed later
# check_row cycles through entire row to ensure uniqueness in the new_value within that row
# @param grid is a list made up of row lists (2D list). Each row list is made up of integers
# @param y_cord is an index pointing to a row list (Y coordinate of the 2D array)
# @param new_value is a randomly generated integer
def check_row(grid, y_cord, new_value):
    print("in chck_row")
    for x_cord in range(9):
        print("in check_row for loop")
        if grid[y_cord][x_cord] == new_value:
            print("check_row returning false")
            return False
    print("check_row returning true")
    return True


# check_col cycles through entire column up to current puzzle depth to ensure uniqueness of new_value within that column
# @param grid is a list made up of row lists. Each row list is made up of integers
# @param new_row is a list of integers ranging from 1 -> 9
# @param number_of_rows is a count of how many rows the current grid contains
def check_col(grid, new_row, number_of_rows):
    for y_cord in range(number_of_rows):
        for i in range(9):
            if grid[y_cord][i] == new_row[i]:
                return False
    return True


# check_box cycles through an entire row of boxes (top, middle, or bottom) to ensure uniqueness. Boxes are numbered 1-9
# @param grid is a list made up of row lists. Each row list is made up of integers
# @param y_cord is an index pointing to a row list (Y coordinate of the 2D array). Used to identify which row to check
# @param number_of_rows is a count of how many rows the current grid contains
def check_box(grid, y_cord, new_row, number_of_rows):
    # checking box 1 (X 0->2 and Y 0->2)
    if y_cord in range(0, 3):
        for x1 in range(0, 3):
            for y1 in range(0, number_of_rows):
                if grid[y1][x1] == new_row[0] or grid[y1][x1] == new_row[1] or grid[y1][x1] == new_row[2]:
                    return False
    # checking box 2 (X 3->5 and Y 0->2)
        for x2 in range(3, 6):
            for y2 in range(0, number_of_rows):
                if grid[y2][x2] == new_row[3] or grid[y2][x2] == new_row[4] or grid[y2][x2] == new_row[5]:
                    return False
    # checking box 3 (X 6->8 and Y 0->2)
        for x3 in range(6, 9):
            for y3 in range(0, number_of_rows):
                if grid[y3][x3] == new_row[6] or grid[y3][x3] == new_row[7] or grid[y3][x3] == new_row[8]:
                    return False
    # checking box 4 (X 0->2 and Y 3->5)
    elif y_cord in range(3, 6):
        for x4 in range(0, 3):
            for y4 in range(3, number_of_rows):
                if grid[y4][x4] == new_row[0] or grid[y4][x4] == new_row[1] or grid[y4][x4] == new_row[2]:
                    return False
    # checking box 5 (X 3->5 and Y 3->5)
        for x5 in range(3, 6):
            for y5 in range(3, number_of_rows):
                if grid[y5][x5] == new_row[3] or grid[y5][x5] == new_row[4] or grid[y5][x5] == new_row[5]:
                    return False
    # checking box 6 (X 6->8 and Y 3->5)
        for x6 in range(6, 9):
            for y6 in range(3, number_of_rows):
                if grid[y6][x6] == new_row[6] or grid[y6][x6] == new_row[7] or grid[y6][x6] == new_row[8]:
                    return False
    # checking box 7 (X 0->2 and Y 6->8)
    elif y_cord in range(6, 9):
        for x7 in range(0, 3):
            for y7 in range(6, number_of_rows):
                if grid[y7][x7] == new_row[0] or grid[y7][x7] == new_row[1] or grid[y7][x7] == new_row[2]:
                    return False
    # checking box 8 (X 3->5 and Y 6->8)
        for x8 in range(3, 6):
            for y8 in range(6, number_of_rows):
                if grid[y8][x8] == new_row[3] or grid[y8][x8] == new_row[4] or grid[y8][x8] == new_row[5]:
                    return False
    # checking box 9 (X 6->8 and Y 6->8)
        for x9 in range(6, 9):
            for y9 in range(6, number_of_rows):
                if grid[y9][x9] == new_row[6] or grid[y9][x9] == new_row[7] or grid[y9][x9] == new_row[8]:
                    return False
    return True
