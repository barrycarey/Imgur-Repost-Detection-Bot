from PIL import Image
from PIL.GifImagePlugin import GifImageFile
from PIL.JpegImagePlugin import JpegImageFile
from PIL.PngImagePlugin import PngImageFile

def dhash(image, hash_size=8):
    """
    Create a hash of the provided image file.
    This function expects and instance of PIL to be passed in.
    """

    if not isinstance(image, (GifImageFile, JpegImageFile, PngImageFile)):
        return False

    # Grayscal and shrink the image in one step
    try:
        image = image.convert('L').resize((hash_size + 1, hash_size), Image.ANTIALIAS)
    except (TypeError, OSError) as e:
        print('Error Creating Image Hash. \n Error Message: {}'.format(e))
        return False

    pixels = list(image.getdata())

    # Compare Ajecent Pixels
    difference = []
    for row in list(range(hash_size)):
        for col in list(range(hash_size)):
            pixel_left = image.getpixel((col, row))
            pixel_right = image.getpixel((col + 1, row))
            difference.append(pixel_left > pixel_right)

    # Convert to binary array to hexadecimal string
    decimal_value = 0
    hex_string = []
    for index, value in enumerate(difference):
        if value:
            decimal_value += 2**(index % 8)
        if (index % 8) == 7:
            hex_string.append(hex(decimal_value)[2:].rjust(2, '0'))
            decimal_value = 0

    return ''.join(hex_string)