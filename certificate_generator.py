from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import qrcode
import os

# --- COLOR PALETTE ---
GOLD_DARK = colors.HexColor('#B8860B')
GOLD_LIGHT = colors.HexColor('#F39C12')
DEEP_BLUE = colors.HexColor('#1A237E')
CHARCOAL = colors.HexColor('#34495E')
OFF_WHITE = colors.HexColor('#FAFAFA')
DEFAULT_VERIFY_BASE_URL = os.getenv('APP_BASE_URL', 'http://127.0.0.1:5000').rstrip('/')

def register_fonts():
    """Attempts to register premium fonts. Falls back to standard."""
    fonts = {
        "HeadingScript": "GreatVibes-Regular.ttf",
        "BodySerif": "PlayfairDisplay-Bold.ttf",
        "BodySans": "Montserrat-Regular.ttf"
    }
    registered = {}
    for name, filename in fonts.items():
        try:
            if os.path.exists(filename):
                pdfmetrics.registerFont(TTFont(name, filename))
                registered[name] = name
            else:
                if name == "HeadingScript": registered[name] = "Times-Italic"
                elif name == "BodySerif": registered[name] = "Times-Bold"
                else: registered[name] = "Helvetica"
        except:
            registered[name] = "Helvetica"
    return registered

def draw_golden_border(c, width, height):
    """Draws an intricate golden floral-style border."""
    # Background wash
    c.setFillColor(OFF_WHITE)
    c.rect(0, 0, width, height, fill=1, stroke=0)

    # Main double frame
    c.setStrokeColor(GOLD_DARK)
    c.setLineWidth(3)
    c.rect(20, 20, width-40, height-40)

    c.setStrokeColor(GOLD_LIGHT)
    c.setLineWidth(1.5)
    c.rect(25, 25, width-50, height-50)

    # Corner Flourishes (Simulated Floral Pattern)
    c.setFillColor(GOLD_DARK)
    c.setStrokeColor(GOLD_LIGHT)
    c.setLineWidth(1)

    corner_size = 80
    # Bottom-Left
    path = c.beginPath()
    path.moveTo(20, 20 + corner_size)
    path.curveTo(20, 20, 20, 20, 20 + corner_size, 20)
    path.curveTo(50, 50, 50, 50, 20, 20 + corner_size)
    path.close()
    c.drawPath(path, fill=1, stroke=1)

    # Top-Right
    path = c.beginPath()
    path.moveTo(width-20, height-20 - corner_size)
    path.curveTo(width-20, height-20, width-20, height-20, width-20 - corner_size, height-20)
    path.curveTo(width-50, height-50, width-50, height-50, width-20, height-20 - corner_size)
    path.close()
    c.drawPath(path, fill=1, stroke=1)

    # Inner Accent Circles
    c.setFillColor(GOLD_LIGHT)
    c.circle(35, 35, 5, fill=1, stroke=0)
    c.circle(width-35, height-35, 5, fill=1, stroke=0)


def draw_decorative_divider(c, x, y, width):
    """Draws a stylish golden divider line."""
    c.setStrokeColor(GOLD_LIGHT)
    c.setLineWidth(1)
    c.line(x, y, x + width, y)
    # Center diamond
    c.setFillColor(GOLD_DARK)
    p = c.beginPath()
    p.moveTo(x + width/2 - 5, y)
    p.lineTo(x + width/2, y + 5)
    p.lineTo(x + width/2 + 5, y)
    p.lineTo(x + width/2, y - 5)
    p.close()
    c.drawPath(p, fill=1, stroke=0)

# UPDATED: Added show_qr=True parameter
def generate_certificate_pdf(student_name, course_name, score, date, attempt_id, cert_type="Completion", show_qr=True):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(letter))
    width, height = landscape(letter)
    fonts = register_fonts()

    # --- 1. BACKGROUND & BORDER ---
    draw_golden_border(c, width, height)

    # --- 2. HEADER SECTION ---
    # Organization Name (Optional Top Header)
    c.setFont(fonts["BodySans"], 10)
    c.setFillColor(CHARCOAL)
    c.drawCentredString(width/2, height - 50, "EXCELLENCE IN EDUCATION & ASSESSMENT")

    # Main Cursive Heading
    if cert_type == "Participation":
        title = "Certificate of Participation"
    else:
        title = "Certificate of Achievement"

    c.setFont(fonts["HeadingScript"], 65)
    c.setFillColor(DEEP_BLUE)
    c.drawCentredString(width/2, height - 120, title)

    # Decorative Divider
    draw_decorative_divider(c, width/2 - 200, height - 150, 400)

    # Presentation Text
    c.setFont(fonts["BodySans"], 11)
    c.setFillColor(CHARCOAL)
    c.drawCentredString(width/2, height - 180, "THIS OFFICIAL DOCUMENT CERTIFIES THAT")

    # --- 3. STUDENT NAME ---
    student_name_str = str(student_name).upper()

    # Golden Underline for Name
    c.setStrokeColor(GOLD_DARK)
    c.setLineWidth(2)
    text_width = c.stringWidth(student_name_str, fonts["BodySerif"], 42)
    c.line(width/2 - text_width/2 - 20, height - 235, width/2 + text_width/2 + 20, height - 235)

    # The Name
    c.setFont(fonts["BodySerif"], 42)
    c.setFillColor(DEEP_BLUE)
    c.drawCentredString(width/2, height - 230, student_name_str)

    # --- 4. BODY CONTENT ---
    c.setFont(fonts["BodySerif"], 16)
    c.setFillColor(CHARCOAL)

    if cert_type == "Participation":
        line1 = "has demonstrated commitment and dedication by actively participating in"
        line3 = ""
    else:
        line1 = "has successfully completed all requisites and demonstrated proficiency in"
        line3 = f"achieving an outstanding score of {score}%."

    c.drawCentredString(width/2, height - 290, line1)

    # Course Name (Prominent)
    c.setFont(fonts["BodySerif"], 26)
    c.setFillColor(DEEP_BLUE)
    c.drawCentredString(width/2, height - 335, str(course_name))

    # Score / Completion Text
    if line3:
        c.setFont(fonts["BodySerif"], 16)
        c.setFillColor(CHARCOAL)
        c.drawCentredString(width/2, height - 375, line3)

    # --- 5. FOOTER SECTION ---
    footer_y = 110

    # Date Section
    c.setFont(fonts["BodySans"], 10)
    c.setFillColor(CHARCOAL)
    c.drawString(120, footer_y + 25, "CERTIFIED ON:")
    c.setFont(fonts["BodySerif"], 14)
    c.drawString(120, footer_y, str(date))
    c.setStrokeColor(GOLD_DARK)
    c.line(115, footer_y - 5, 250, footer_y - 5)

    # Signature Section
    c.setStrokeColor(GOLD_DARK)
    c.line(width - 300, footer_y - 5, width - 120, footer_y - 5)
    c.setFont(fonts["BodySans"], 10)
    c.drawCentredString(width - 210, footer_y - 25, "PROGRAM DIRECTOR SIGNATURE")

    # --- 6. IMAGES & VALIDATION ---
    try:
        # --- A. Signature Image ---
        # Absolute path as requested
        sig_path = "/home/Rahul02100/Quize/quize/static/signature.png"

        if os.path.exists(sig_path):
            c.drawImage(sig_path, width - 290, footer_y, width=160, height=60, mask='auto')
        else:
            print(f"Warning: Signature not found at {sig_path}")

        # --- B. Gold Seal (Bottom Center) ---
        seal_y = 60
        c.setFillColor(colors.HexColor('#B8860B')) # Gold
        c.circle(width/2, seal_y, 30, fill=1, stroke=0)
        c.setFillColor(colors.HexColor('#FAFAFA')) # White inner
        c.circle(width/2, seal_y, 25, fill=1, stroke=0)

        c.setFont(fonts["BodySerif"], 8)
        c.setFillColor(colors.HexColor('#B8860B'))
        c.drawCentredString(width/2, seal_y + 3, "OFFICIAL")
        c.drawCentredString(width/2, seal_y - 7, "SEAL")

        # --- C. QR Code (Centered ABOVE the Seal) ---
        # UPDATED: Only generate QR if show_qr is True
        if show_qr:
            verify_url = f"{DEFAULT_VERIFY_BASE_URL}/verify/{attempt_id}"

            qr = qrcode.QRCode(box_size=10, border=1)
            qr.add_data(verify_url)
            qr.make(fit=True)

            qr_img = qr.make_image(fill_color="#1A237E", back_color="white")

            qr_buffer = io.BytesIO()
            qr_img.save(qr_buffer, format="PNG")
            qr_buffer.seek(0)

            # Center Math
            qr_size = 70
            qr_x = (width / 2) - (qr_size / 2)
            qr_y = seal_y + 35

            c.drawImage(ImageReader(qr_buffer), qr_x, qr_y, qr_size, qr_size)

            # "Scan to Verify" Label
            c.setFont(fonts["BodySans"], 7)
            c.setFillColor(colors.HexColor('#B8860B'))
            c.drawCentredString(width/2, qr_y - 8, "SCAN TO VERIFY")
        else:
            # Manual Issue Label if no QR
            c.setFont(fonts["BodySans"], 8)
            c.setFillColor(colors.HexColor('#B8860B'))
            c.drawCentredString(width/2, seal_y + 40, "OFFICIALLY ISSUED")

    except Exception as e:
        print(f"--- Certificate Image Error: {e} ---")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer
