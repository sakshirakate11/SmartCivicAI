import categoryDepartments from '../category_departments.json'

export function compressComplaintImage(file) {
  if (file.size > 10 * 1024 * 1024) {
    return Promise.reject(new Error('Choose an image smaller than 10 MB.'))
  }
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    return Promise.reject(new Error('Choose a JPG, PNG, or WebP image.'))
  }

  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('The selected image could not be read.'))
    reader.onload = () => {
      const image = new Image()
      image.onerror = () => reject(new Error('The selected file is not a readable image.'))
      image.onload = () => {
        const scale = Math.min(1, 1000 / Math.max(image.width, image.height))
        const canvas = document.createElement('canvas')
        canvas.width = Math.max(1, Math.round(image.width * scale))
        canvas.height = Math.max(1, Math.round(image.height * scale))
        const context = canvas.getContext('2d')
        if (!context) {
          reject(new Error('Image preview is unavailable in this browser.'))
          return
        }
        context.drawImage(image, 0, 0, canvas.width, canvas.height)
        resolve(canvas.toDataURL('image/jpeg', 0.68))
      }
      image.src = reader.result
    }
    reader.readAsDataURL(file)
  })
}

const actionsByCategory = {
  'Roads & pathways': 'Inspect the affected road segment, mark any immediate hazard, and schedule a surface repair.',
  'Waste management': 'Check the collection route and bin capacity, then schedule a cleanup or missed pickup.',
  'Water supply': 'Inspect nearby water mains, isolate any leak, and prioritize public-safety risks.',
  'Drainage & flooding': 'Inspect nearby drains, clear blockages, and prioritize public-safety risks.',
  'Street lighting': 'Inspect the nearest lighting circuit and arrange a lamp or power-supply repair.',
  'Public health': 'Arrange a site assessment and refer any immediate health risk to the appropriate city team.',
  'Parks & gardens': 'Inspect the public space and schedule the required maintenance or safety work.',
  Other: 'Review the report details and route it to the city team best placed to resolve it.',
}

export function getCategoryAdvice(category = '') {
  const resolvedCategory = Object.hasOwn(categoryDepartments, category) ? category : 'Other'
  return {
    department: categoryDepartments[resolvedCategory],
    action: actionsByCategory[resolvedCategory],
  }
}
