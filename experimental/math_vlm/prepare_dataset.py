#!/usr/bin/env python3
import os
import json
import matplotlib
# Headless mode for matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def render_latex(formula_str, save_path):
    """
    Renders a LaTeX math formula string into a high-quality PNG image.
    """
    # Create figure with a size that fits a typical math expression
    fig = plt.figure(figsize=(4.5, 1.5), dpi=150)
    # Render text in math mode
    plt.text(0.5, 0.5, f"${formula_str}$", size=26, ha='center', va='center', color='black')
    plt.axis('off')
    
    # Save the rendered figure
    plt.savefig(save_path, bbox_inches='tight', pad_inches=0.15, facecolor='white', edgecolor='none')
    plt.close(fig)

def generate_math_expressions():
    """
    Generates template math formulas and their matching spoken English descriptions.
    """
    dataset = []
    
    # Let's define variables to loop over for variance
    vars_list = [
        ('x', 'y', 'z'),
        ('a', 'b', 'c'),
        ('u', 'v', 'w'),
        ('p', 'q', 'r')
    ]
    
    for v1, v2, v3 in vars_list:
        # Addition / Subtraction
        dataset.append((f"{v1} + {v2}", f"{v1} plus {v2}"))
        dataset.append((f"{v1} - {v2}", f"{v1} minus {v2}"))
        dataset.append((f"{v1} + {v2} - {v3}", f"{v1} plus {v2} minus {v3}"))
        
        # Basic products
        dataset.append((f"{v1} {v2}", f"{v1} times {v2}"))
        dataset.append((f"{v1} \\cdot {v2}", f"{v1} times {v2}"))
        dataset.append((f"{v1} \\times {v2}", f"{v1} times {v2}"))
        
        # Fractions
        dataset.append((f"\\frac{{{v1}}}{{{v2}}}", f"fraction {v1} over {v2}"))
        dataset.append((f"\\frac{{{v1} + {v2}}}{{{v3}}}", f"fraction {v1} plus {v2} over {v3}"))
        
        # Exponents and Subscripts
        dataset.append((f"{v1}^2", f"{v1} squared"))
        dataset.append((f"{v1}^3", f"{v1} cubed"))
        dataset.append((f"{v1}^n", f"{v1} to the power of n"))
        dataset.append((f"{v1}^{v2}", f"{v1} to the power of {v2}"))
        dataset.append((f"{v1}_i", f"{v1} sub i"))
        dataset.append((f"{v1}_{{i+1}}", f"{v1} sub i plus one"))
        dataset.append((f"{v1}_{{t-1}}", f"{v1} sub t minus one"))
        
        # Integrals
        dataset.append((f"\\int {v1} \\, d{v1}", f"integral of {v1} d {v1}"))
        dataset.append((f"\\int {v1}^2 \\, d{v1}", f"integral of {v1} squared d {v1}"))
        dataset.append((f"\\int_{{a}}^{{b}} {v1} \\, d{v1}", f"integral from a to b of {v1} d {v1}"))
        dataset.append((f"\\int_{{0}}^{{1}} {v1}^2 \\, d{v1}", f"integral from zero to one of {v1} squared d {v1}"))
        
        # Sums
        dataset.append((f"\\sum {v1}_i", f"sum of {v1} sub i"))
        dataset.append((f"\\sum_{{i=1}}^{{n}} {v1}_i", f"sum from i equals one to n of {v1} sub i"))
        
        # Square Roots
        dataset.append((f"\\sqrt{{{v1}}}", f"square root of {v1}"))
        dataset.append((f"\\sqrt{{{v1}^2 + {v2}^2}}", f"square root of {v1} squared plus {v2} squared"))
        
        # Equations
        dataset.append((f"{v1}^2 + {v2}^2 = {v3}^2", f"{v1} squared plus {v2} squared equals {v3} squared"))
        dataset.append((f"f({v1}) = {v1}^2", f"f of {v1} equals {v1} squared"))

    # Additional standard formulas
    extra = [
        ("E = mc^2", "E equals m c squared"),
        ("F = ma", "F equals m a"),
        ("\\log(x)", "log of x"),
        ("\\sin(\\theta)", "sine of theta"),
        ("\\cos(x)", "cosine of x"),
        ("e^{i \\pi} + 1 = 0", "e to the power of i pi plus one equals zero"),
        ("a(b + c) = ab + ac", "a times open parenthesis b plus c close parenthesis equals a b plus a c"),
        ("\\frac{1}{2}", "one half"),
        ("\\frac{1}{3}", "one third"),
        ("\\frac{1}{4}", "one quarter"),
    ]
    dataset.extend(extra)
    
    return dataset

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "dataset")
    images_dir = os.path.join(dataset_dir, "images")
    
    os.makedirs(images_dir, exist_ok=True)
    
    print("[PREPARE] Generating math expressions and spoken captions...")
    expressions = generate_math_expressions()
    
    metadata = []
    
    print(f"[PREPARE] Rendering {len(expressions)} expressions to PNG...")
    for idx, (latex, spoken) in enumerate(expressions):
        img_filename = f"math_{idx:04d}.png"
        img_path = os.path.join(images_dir, img_filename)
        
        # Render image
        try:
            render_latex(latex, img_path)
            
            # Save relative path in metadata
            metadata.append({
                "image": os.path.join("images", img_filename),
                "latex": latex,
                "spoken": spoken
            })
        except Exception as e:
            print(f"Error rendering {latex}: {e}")
            
    # Write metadata.json
    metadata_path = os.path.join(dataset_dir, "metadata.json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=4)
        
    print(f"[PREPARE] Dataset prepared successfully!")
    print(f"  - Images saved to: {images_dir}")
    print(f"  - Metadata saved to: {metadata_path}")
    print(f"  - Total samples generated: {len(metadata)}")

if __name__ == "__main__":
    main()
